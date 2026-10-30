
import { useCallback, useEffect, useState } from "react";

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

const apiBaseUrl = configuredApiBaseUrl
  ? (
      /^https?:\/\//i.test(configuredApiBaseUrl)
        ? configuredApiBaseUrl
        : `https://${configuredApiBaseUrl}`
    ).replace(/\/+$/, "")
  : "";

const configurationLabels = {
  paypal_client_id: "PayPal Client ID",
  paypal_client_secret: "PayPal Client Secret",
  paypal_base_url: "PayPal API Base URL",
  paypal_webhook_id: "PayPal Webhook ID",
  database_url: "Database URL",
  llm_provider: "LLM Provider",
  llm_api_key: "LLM API Key",
  llm_model: "LLM Model",
  frontend_origin: "Frontend Origin",
  pending_threshold_minutes: "Pending Threshold",
};


async function fetchJson(path) {
  const response = await fetch(`${apiBaseUrl}${path}`);

  if (!response.ok) {
    throw new Error(`Request failed (${response.status}) for ${path}`);
  }

  return response.json();
}

async function postJson(path, body) {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  const payload = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(
      typeof payload.detail === "string"
        ? payload.detail
        : `Request failed (${response.status})`
    );
  }

  return payload;
}
function formatDate(value) {
  if (!value) return "Not available";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return date.toLocaleString();
}

function formatStatus(value) {
  if (!value) return "Unknown";

  return String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function StatusBadge({ value }) {
  const normalized = String(value ?? "unknown").toLowerCase();

  return (
    <span className={`evidence-badge evidence-${normalized}`}>
      {formatStatus(value)}
    </span>
  );
}

function ConfigurationList({ config }) {
  if (!config || typeof config !== "object") {
    return <p className="empty-state">Configuration status unavailable.</p>;
  }

  return (
    <ul className="config-list">
      {Object.entries(configurationLabels).map(([key, label]) => {
        const present = config[key];

        return (
          <li key={key}>
            <span>{label}</span>
            <strong className={present ? "config-present" : "config-missing"}>
              {present ? "Present" : "Missing"}
            </strong>
          </li>
        );
      })}
    </ul>
  );
}

function IncidentBadges({ incident }) {
  const severity = String(incident.severity ?? "unknown").toLowerCase();
  const status = String(incident.status ?? "unknown").toLowerCase();

  return (
    <div className="incident-badges">
      <span className={`severity severity-${severity}`}>{severity}</span>
      <span className={`status status-${status}`}>{status}</span>
    </div>
  );
}

function IncidentCard({ incident, onSelect }) {
  const evidenceCount = Array.isArray(incident.evidence_event_ids)
    ? incident.evidence_event_ids.length
    : 0;

  return (
    <button
      type="button"
      className="incident incident-card-button"
      onClick={() => onSelect(incident)}
      aria-label={`View details for incident ${incident.id}: ${incident.rule_id}`}
    >
      <div className="incident-top">
        <strong className="rule-id">
          {incident.rule_id ?? "Unknown incident"}
        </strong>
        <IncidentBadges incident={incident} />
      </div>

      <p className="incident-description">
        {incident.description ?? "No description provided."}
      </p>

      <div className="incident-meta">
        <span>Incident #{incident.id}</span>
        <span>Order ID: {incident.order_id ?? "N/A"}</span>
        <span>Evidence events: {evidenceCount}</span>
      </div>

      <p className="incident-time">
        Created: {formatDate(incident.created_at)}
      </p>

      <span className="incident-open-hint">View incident details →</span>
    </button>
  );
}


function IncidentDetails({ incident, onBack }) {
  const evidenceIds = Array.isArray(incident.evidence_event_ids)
    ? incident.evidence_event_ids
    : [];

  const [question, setQuestion] = useState(
    "Why was this incident detected, and what should I verify?"
  );
  const [report, setReport] = useState(null);
  const [investigating, setInvestigating] = useState(false);
  const [investigationError, setInvestigationError] = useState("");

  async function handleInvestigate() {
    if (!question.trim()) {
      setInvestigationError("Please enter an investigation question.");
      return;
    }

    setInvestigating(true);
    setInvestigationError("");
    setReport(null);

    try {
      const result = await postJson(
        `/api/incidents/${incident.id}/investigate`,
        { question: question.trim() }
      );

      setReport(result);
    } catch (error) {
      setInvestigationError(error.message || "Investigation failed.");
    } finally {
      setInvestigating(false);
    }
  }

  return (
    <div className="incident-details">
      <button type="button" className="refresh-button" onClick={onBack}>
        Back to incidents
      </button>

      <section className="detail-section">
        <h3>Incident details</h3>

        
<div className="evidence-card-grid">
  <article className="evidence-card">
    <h4>Event information</h4>
    <dl>
      <div>
        <dt>Event type</dt>
        <dd>{selectedEvent.event_type || "Unknown"}</dd>
      </div>
      <div>
        <dt>PayPal event ID</dt>
        <dd>{selectedEvent.paypal_event_id || "Not available"}</dd>
      </div>
      <div>
        <dt>Resource ID</dt>
        <dd>{selectedEvent.resource_id || "Not available"}</dd>
      </div>
    </dl>
  </article>

  <article className="evidence-card">
    <h4>Order relationship</h4>
    <dl>
      <div>
        <dt>Local order ID</dt>
        <dd>{selectedEvent.order_id ?? "Not linked"}</dd>
      </div>
      <div>
        <dt>PayPal order reference</dt>
        <dd>{selectedEvent.paypal_order_ref || "Not available"}</dd>
      </div>
      <div>
        <dt>Source</dt>
        <dd>{formatStatus(selectedEvent.source)}</dd>
      </div>
    </dl>
  </article>

  <article className="evidence-card">
    <h4>Verification</h4>
    <dl>
      <div>
        <dt>Verification status</dt>
        <dd>
          <StatusBadge value={selectedEvent.verification_status} />
        </dd>
      </div>
      <div>
        <dt>Duplicate delivery</dt>
        <dd>
          <StatusBadge
            value={
              selectedEvent.is_duplicate_delivery
                ? "duplicate"
                : "not_duplicate"
            }
          />
        </dd>
      </div>
    </dl>
  </article>

  <article className="evidence-card">
    <h4>Event timestamps</h4>
    <dl>
      <div>
        <dt>Delivery received</dt>
        <dd>{formatDate(selectedEvent.delivery_received_at)}</dd>
      </div>
      <div>
        <dt>Event created</dt>
        <dd>{formatDate(selectedEvent.event_created_at)}</dd>
      </div>
      <div>
        <dt>Processed</dt>
        <dd>{formatDate(selectedEvent.processed_at)}</dd>
      </div>
    </dl>
  </article>
</div>

      </section>

      <section className="detail-section">
        <h4>Evidence events</h4>

        {evidenceIds.length > 0 ? (
          <ul className="evidence-list">
            {evidenceIds.map((eventId) => (
              <li key={eventId}>Event ID: {eventId}</li>
            ))}
          </ul>
        ) : (
          <p className="empty-state">
            No evidence events are linked to this incident.
            This does not prove that no payment events exist.
          </p>
        )}
      </section>

      <section className="detail-section investigation-section">
        <h3>Incident investigation</h3>

        <p>
          Ask a question about this incident. PayTrace AI will examine
          the stored incident information and available evidence.
        </p>

        <label htmlFor="investigation-question">
          Investigation question
        </label>

        <textarea
          id="investigation-question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          rows={3}
          maxLength={4000}
          placeholder="Ask a question about this incident..."
        />

        <button
          type="button"
          className="refresh-button"
          onClick={handleInvestigate}
          disabled={investigating || !question.trim()}
        >
          {investigating ? "Investigating..." : "Investigate incident"}
        </button>

        {investigationError && (
          <p className="error-message">{investigationError}</p>
        )}

        {report && (
          <div className="investigation-report">
            <h4>Investigation report</h4>

            <p>
              <strong>Generated by:</strong>{" "}
              {report.generated_by || "Deterministic analysis"}
            </p>

            <section>
              <h4>Summary</h4>
              <p>{report.summary}</p>
            </section>

            <section>
              <h4>Findings</h4>
              {report.findings?.length > 0 ? (
                <ul>
                  {report.findings.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p>No findings available.</p>
              )}
            </section>

            <section>
              <h4>Possible explanations</h4>
              {report.hypotheses?.length > 0 ? (
                <ul>
                  {report.hypotheses.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p>No hypotheses available.</p>
              )}
            </section>

            <section>
              <h4>Recommended checks</h4>
              {report.recommended_checks?.length > 0 ? (
                <ul>
                  {report.recommended_checks.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p>No recommended checks available.</p>
              )}
            </section>

            <section>
              <h4>Investigation evidence</h4>
              {report.evidence?.length > 0 ? (
                <ul>
                  {report.evidence.map((item, index) => (
                    <li key={index}>
                      <pre>
                        {JSON.stringify(item, null, 2)}
                      </pre>
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No evidence was returned.</p>
              )}
            </section>

            <section>
              <h4>Limitations</h4>
              {report.limitations?.length > 0 ? (
                <ul>
                  {report.limitations.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p>No limitations reported.</p>
              )}
            </section>
          </div>
        )}
      </section>

      <p className="detail-safety-note">
        Verify the current payment state with PayPal before taking action.
        This investigation is advisory only and does not perform payment
        operations.
      </p>
    </div>
  );
}


function EventExplorer() {
  const [events, setEvents] = useState([]);
  const [total, setTotal] = useState(0);
  const [source, setSource] = useState("");
  const [eventType, setEventType] = useState("");
  const [orderId, setOrderId] = useState("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedEvent, setSelectedEvent] = useState(null);

  const limit = 20;

  const loadEvents = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const params = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
      });

      if (source) params.set("source", source);
      if (eventType.trim()) {
        params.set("event_type", eventType.trim());
      }
      if (orderId.trim()) {
        if (!/^\d+$/.test(orderId.trim())) {
          throw new Error("Order ID must be a positive integer.");
        }
        params.set("order_id", orderId.trim());
      }

      const result = await fetchJson(
        `/api/events?${params.toString()}`
      );

      setEvents(Array.isArray(result.items) ? result.items : []);
      setTotal(Number(result.total) || 0);
      setSelectedEvent(null);
    } catch (err) {
      setEvents([]);
      setTotal(0);
      setError(err.message || "Could not load events.");
    } finally {
      setLoading(false);
    }
  }, [source, eventType, orderId, offset]);

  useEffect(() => {
    loadEvents();
  }, [loadEvents]);

  function applyFilters(event) {
    event.preventDefault();
    setOffset(0);
    // The effect loads the events when offset changes.
    // If already at offset zero, load directly.
    if (offset === 0) loadEvents();
  }

  const pageNumber = Math.floor(offset / limit) + 1;
  const pageCount = Math.max(1, Math.ceil(total / limit));

  return (
    <section className="panel events-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">PAYMENT OBSERVABILITY</p>
          <h2>Event Explorer</h2>
          <p className="intro">
            Inspect stored payment events and webhook verification metadata.
          </p>
        </div>
        <button
          type="button"
          className="refresh-button"
          onClick={loadEvents}
          disabled={loading}
        >
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {selectedEvent ? (
        <div className="event-details">
          <button
            type="button"
            className="refresh-button"
            onClick={() => setSelectedEvent(null)}
          >
            ← Back to events
          </button>

          <h3>Event #{selectedEvent.id}</h3>
          <dl className="detail-grid">
            {[
              ["Event type", selectedEvent.event_type],
              ["PayPal event ID", selectedEvent.paypal_event_id],
              ["Source", selectedEvent.source],
              ["Order ID", selectedEvent.order_id],
              ["PayPal order reference", selectedEvent.paypal_order_ref],
              ["Resource ID", selectedEvent.resource_id],
              ["Verification", selectedEvent.verification_status],
              ["Duplicate delivery", selectedEvent.is_duplicate_delivery ? "Yes" : "No"],
              ["Received at", formatDate(selectedEvent.delivery_received_at)],
              ["Event created at", formatDate(selectedEvent.event_created_at)],
              ["Processed at", formatDate(selectedEvent.processed_at)],
            ].map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value == null || value === "" ? "Not available" : String(value)}</dd>
              </div>
            ))}
          </dl>

          <p className="detail-safety-note">
            Raw webhook payloads are not displayed. Verification metadata
            does not by itself establish the current payment state.
          </p>
        </div>
      ) : (
        <>
          <form className="event-filters" onSubmit={applyFilters}>
            <label>
              Source
              <select
                value={source}
                onChange={(e) => {
                  setSource(e.target.value);
                  setOffset(0);
                }}
              >
                <option value="">All sources</option>
                <option value="paypal_sandbox">PayPal Sandbox</option>
                <option value="simulated">Simulated</option>
              </select>
            </label>

            <label>
              Event type
              <input
                value={eventType}
                onChange={(e) => setEventType(e.target.value)}
                placeholder="e.g. PAYMENT.CAPTURE.COMPLETED"
              />
            </label>

            <label>
              Order ID
              <input
                inputMode="numeric"
                value={orderId}
                onChange={(e) => setOrderId(e.target.value)}
                placeholder="Database order ID"
              />
            </label>

            <button type="submit" className="refresh-button">
              Apply filters
            </button>
          </form>

          {error && <p className="error-message">{error}</p>}

          <div className="event-summary">
            {total} matching event{total === 1 ? "" : "s"}
          </div>

          {loading ? (
            <p className="empty-state">Loading events...</p>
          ) : error ? null : events.length === 0 ? (
            <p className="empty-state">
              No stored events match these filters. This does not prove
              that PayPal has no events.
            </p>
          ) : (
            <div className="event-table-wrap">
              <table className="event-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Event type</th>
                    <th>Source</th>
                    <th>Order ID</th>
                    <th>Verification</th>
                    <th>Received</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((item) => (
                    <tr key={item.id}>
                      <td>{item.id}</td>
                      <td>{item.event_type || "Unknown"}</td>
                      <td>{item.source || "Unknown"}</td>
                      <td>{item.order_id ?? "—"}</td>
                      <td>{item.verification_status || "Unknown"}</td>
                      <td>{formatDate(item.delivery_received_at)}</td>
                      <td>
                        <button
                          type="button"
                          className="event-detail-button"
                          onClick={() => setSelectedEvent(item)}
                        >
                          Inspect
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="event-pagination">
            <button
              type="button"
              className="refresh-button"
              disabled={loading || offset === 0}
              onClick={() => setOffset(Math.max(0, offset - limit))}
            >
              Previous
            </button>
            <span>Page {pageNumber} of {pageCount}</span>
            <button
              type="button"
              className="refresh-button"
              disabled={loading || offset + limit >= total}
              onClick={() => setOffset(offset + limit)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </section>
  );
}
export default function App() {
  const [health, setHealth] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [healthError, setHealthError] = useState("");
  const [incidentsError, setIncidentsError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadDashboard = useCallback(async (isRefresh = false) => {
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    setHealthError("");
    setIncidentsError("");

    try {
      const [healthResult, incidentsResult] = await Promise.allSettled([
        fetchJson("/api/health"),
        fetchJson("/api/incidents"),
      ]);

      if (healthResult.status === "fulfilled") {
        setHealth(healthResult.value);
      } else {
        setHealthError(
          healthResult.reason?.message ?? "Could not load backend health."
        );
      }

      if (incidentsResult.status === "fulfilled") {
        const result = incidentsResult.value;
        const nextIncidents = Array.isArray(result)
          ? result
          : result.items ?? [];

        setIncidents(nextIncidents);

        setSelectedIncident((current) =>
          current
            ? nextIncidents.find((item) => item.id === current.id) ?? null
            : null
        );
      } else {
        setIncidentsError(
          incidentsResult.reason?.message ?? "Could not load incidents."
        );
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  return (
    <main className="page">
      <header className="page-header">
        <h1>PayTrace AI</h1>
        <p>
          Understand payment events and investigate integration issues.
          PayTrace AI is an observability tool, not a payment processor.
        </p>
      </header>

      <section className="panel health-panel">
        <h2>Backend health</h2>

        {healthError ? (
          <p className="error-message">{healthError}</p>
        ) : health ? (
          <p>
            <span
              className={`health-indicator ${
                health.status === "ok" ? "health-ok" : "health-error"
              }`}
            />
            <strong>{health.status}</strong>
          </p>
        ) : (
          <p>{loading ? "Checking backend..." : "Health unavailable."}</p>
        )}

        <details className="configuration-details">
          <summary>Configuration presence (values are never shown)</summary>
          {health?.config_present ? (
            <ConfigurationList config={health.config_present} />
          ) : (
            <p className="empty-state">
              Configuration status is unavailable.
            </p>
          )}
        </details>
      </section>

      <section className="panel incidents-panel">
        {selectedIncident ? (
          <IncidentDetails
            incident={selectedIncident}
            onBack={() => setSelectedIncident(null)}
          />
        ) : (
          <>
            <div className="section-heading">
              <div>
                <p className="eyebrow">MONITORING</p>
                <h2>Incidents</h2>
                <p>Detected integration issues requiring investigation.</p>
              </div>

              <button
                type="button"
                className="refresh-button"
                onClick={() => loadDashboard(true)}
                disabled={refreshing}
              >
                {refreshing ? "Refreshing..." : "Refresh"}
              </button>
            </div>

            {incidentsError && (
              <p className="error-message">{incidentsError}</p>
            )}

            {loading ? (
              <p className="empty-state">Loading incidents...</p>
            ) : incidents.length === 0 && !incidentsError ? (
              <p className="empty-state">No incidents found.</p>
            ) : (
              <div className="incident-list">
                {incidents.map((incident) => (
                  <IncidentCard
                    key={incident.id}
                    incident={incident}
                    onSelect={setSelectedIncident}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </section>
      <EventExplorer />
      <footer className="page-footer">
        Always verify payment state with PayPal before taking action.
      </footer>
    </main>
  );
}