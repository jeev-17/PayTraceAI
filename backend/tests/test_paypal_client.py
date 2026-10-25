
import httpx
import pytest

from app.services.paypal_client import PayPalClient, PayPalError


def make_client(handler):
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)

    client = PayPalClient(
        base_url="https://api-m.sandbox.paypal.com",
        client_id="test-client-id",
        client_secret="test-client-secret",
        http_client=http_client,
    )

    return client, http_client


def test_missing_credentials():
    client = PayPalClient(
        client_id="",
        client_secret="",
    )

    try:
        with pytest.raises(PayPalError, match="credentials are not configured"):
            client._access_token()
    finally:
        client.close()


def test_access_token_is_cached():
    calls = {"token": 0}

    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            calls["token"] += 1
            return httpx.Response(
                200,
                json={"access_token": "test-token", "expires_in": 3600},
            )

        return httpx.Response(500)

    client, http_client = make_client(handler)

    try:
        assert client._access_token() == "test-token"
        assert client._access_token() == "test-token"
        assert calls["token"] == 1
    finally:
        client.close()
        http_client.close()



def test_create_order_sends_expected_payload():
    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(
                200,
                json={"access_token": "test-token", "expires_in": 3600},
            )

        assert request.method == "POST"
        assert request.url.path == "/v2/checkout/orders"
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.headers["PayPal-Request-Id"] == (
            "paytrace-create-test-001"
        )

        payload = request.read().decode()
        assert '"intent":"CAPTURE"' in payload
        assert '"currency_code":"USD"' in payload
        assert '"value":"12.50"' in payload
        assert '"reference_id":"test-order-1"' in payload

        return httpx.Response(
            201,
            json={"id": "SANDBOX-ORDER-1", "status": "CREATED"},
        )

    client, http_client = make_client(handler)

    try:
        result = client.create_order(
            amount="12.50",
            currency="USD",
            reference="test-order-1",
            request_id="paytrace-create-test-001",
        )
        assert result["id"] == "SANDBOX-ORDER-1"
    finally:
        client.close()
        http_client.close()


def test_capture_timeout_is_marked_uncertain():
    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(
                200,
                json={"access_token": "test-token", "expires_in": 3600},
            )

        raise httpx.ReadTimeout("simulated timeout", request=request)

    client, http_client = make_client(handler)

    try:
        with pytest.raises(PayPalError) as exc_info:
            client.capture_order("SANDBOX-ORDER-1")

        assert exc_info.value.uncertain is True
        assert "verify the order" in str(exc_info.value).lower()
    finally:
        client.close()
        http_client.close()