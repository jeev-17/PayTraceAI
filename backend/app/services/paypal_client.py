
import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class PayPalError(Exception):
    """Safe error raised for PayPal API failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        debug_id: str | None = None,
        uncertain: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.debug_id = debug_id
        self.uncertain = uncertain


class PayPalClient:
    """Small PayPal REST client configured for Sandbox use."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        timeout: float = 10.0,
        http_client: httpx.Client | None = None,
    ):
        self.base_url = (
            base_url or settings.paypal_base_url
        ).rstrip("/")
        self.client_id = client_id or settings.paypal_client_id
        self.client_secret = (
            client_secret or settings.paypal_client_secret
        )
        self.timeout = timeout
        self._http = http_client or httpx.Client(timeout=timeout)
        self._owns_http = http_client is None
        self._token: str | None = None
        self._token_expires_at = 0.0

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token

        if not self.client_id or not self.client_secret:
            raise PayPalError(
                "PayPal Sandbox credentials are not configured."
            )

        try:
            response = self._http.post(
                f"{self.base_url}/v1/oauth2/token",
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json"},
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise PayPalError(
                "PayPal authentication timed out."
            ) from exc
        except httpx.RequestError as exc:
            raise PayPalError(
                "PayPal authentication could not reach the service."
            ) from exc

        if not response.is_success:
            raise PayPalError(
                "PayPal authentication failed.",
                status_code=response.status_code,
                debug_id=response.headers.get("PayPal-Debug-Id"),
            )

        try:
            data = response.json()
            token = data["access_token"]
            expires_in = int(data.get("expires_in", 300))

            if not isinstance(token, str) or not token:
                raise ValueError("Invalid access token")
        except (ValueError, KeyError, TypeError) as exc:
            raise PayPalError(
                "PayPal returned an invalid authentication response."
            ) from exc

        self._token = token
        self._token_expires_at = (
            time.monotonic() + max(0, expires_in - 60)
        )
        return self._token

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        request_id: str | None = None,
        outcome_may_be_uncertain: bool = False,
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        if request_id:
            headers["PayPal-Request-Id"] = request_id

        try:
            response = self._http.request(
                method,
                f"{self.base_url}{path}",
                json=json,
                headers=headers,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise PayPalError(
                "PayPal request timed out; verify the order before taking further action.",
                uncertain=outcome_may_be_uncertain,
            ) from exc
        except httpx.RequestError as exc:
            raise PayPalError(
                "PayPal request failed; verify the order before taking further action.",
                uncertain=outcome_may_be_uncertain,
            ) from exc

        debug_id = response.headers.get("PayPal-Debug-Id")

        if not response.is_success:
            raise PayPalError(
                "PayPal rejected the request or returned a server error.",
                status_code=response.status_code,
                debug_id=debug_id,
                uncertain=(
                    outcome_may_be_uncertain
                    and response.status_code >= 500
                ),
            )

        try:
            result = response.json()
        except ValueError as exc:
            raise PayPalError(
                "PayPal returned an invalid response.",
                status_code=response.status_code,
                debug_id=debug_id,
                uncertain=outcome_may_be_uncertain,
            ) from exc

        if not isinstance(result, dict):
            raise PayPalError(
                "PayPal returned an unexpected response.",
                status_code=response.status_code,
                debug_id=debug_id,
                uncertain=outcome_may_be_uncertain,
            )

        if debug_id:
            logger.info("PayPal request completed; debug_id=%s", debug_id)

        return result

    def create_order(
        self,
        amount: str,
        currency: str,
        reference: str,
        request_id: str,
    ) -> dict:
        if not request_id:
            raise ValueError("A stable request_id is required.")

        return self._request(
            "POST",
            "/v2/checkout/orders",
            request_id=request_id,
            outcome_may_be_uncertain=True,
            json={
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "reference_id": reference,
                        "amount": {
                            "currency_code": currency,
                            "value": amount,
                        },
                    }
                ],
            },
        )

    def capture_order(self, paypal_order_id: str) -> dict:
        return self._request(
            "POST",
            f"/v2/checkout/orders/{paypal_order_id}/capture",
            request_id=f"paytrace-capture-{paypal_order_id}",
            json={},
            outcome_may_be_uncertain=True,
        )

    def get_order(self, paypal_order_id: str) -> dict:
        return self._request(
            "GET",
            f"/v2/checkout/orders/{paypal_order_id}",
        )

    
    def verify_webhook_signature(
        self,
        headers: dict[str, str],
        webhook_id: str,
        webhook_event: dict,
    ) -> bool:
        """Ask PayPal to verify a webhook's signature."""

        required_headers = {
            "auth_algo": "paypal-auth-algo",
            "cert_url": "paypal-cert-url",
            "transmission_id": "paypal-transmission-id",
            "transmission_sig": "paypal-transmission-sig",
            "transmission_time": "paypal-transmission-time",
        }

        normalized_headers = {
            key.lower(): value
            for key, value in headers.items()
        }

        verification_payload = {}
        missing_headers = []

        for payload_key, header_key in required_headers.items():
            value = normalized_headers.get(header_key)

            if not value:
                missing_headers.append(header_key)
            else:
                verification_payload[payload_key] = value

        if missing_headers:
            logger.warning(
                "PayPal webhook verification rejected: missing headers %s",
                missing_headers,
            )
            return False

        if not webhook_id or not isinstance(webhook_event, dict):
            logger.warning(
                "PayPal webhook verification rejected: webhook ID or event is invalid."
            )
            return False

        verification_payload["webhook_id"] = webhook_id
        verification_payload["webhook_event"] = webhook_event

        result = self._request(
            "POST",
            "/v1/notifications/verify-webhook-signature",
            json=verification_payload,
        )

        logger.info(
            "PayPal verification response status: %s",
            result.get("verification_status"),
        )
        logger.info(
            "PayPal verification response debug ID: %s",
            result.get("debug_id"),
        )

        verification_status = result.get("verification_status")

        if verification_status != "SUCCESS":
            logger.warning(
                "PayPal webhook signature verification returned status: %s",
                verification_status,
            )
            return False

        logger.info("PayPal webhook signature verified successfully.")
        return True
