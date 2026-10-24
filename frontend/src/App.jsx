import { useEffect, useState } from "react";

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";
const apiBaseUrl = configuredApiBaseUrl
  ? (
      /^https?:\/\//i.test(configuredApiBaseUrl)
        ? configuredApiBaseUrl
        : `https://${configuredApiBaseUrl}`
    ).replace(/\/+$/, "")
  : "";

export default function App() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();

    fetch(`${apiBaseUrl}/api/health`, { signal: controller.signal })
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) {
          throw new Error(body.error?.message ?? "Health check failed.");
        }
        setHealth(body);
      })
      .catch((requestError) => {
        if (requestError.name !== "AbortError") {
          setError(requestError.message);
        }
      });

    return () => controller.abort();
  }, []);

  return (
    <main className="page">
      <section className="card" aria-labelledby="title">
        <p className="eyebrow">PAYMENT DEBUGGING WORKBENCH</p>
        <h1 id="title">PayTrace AI</h1>
        <p className="intro">
          Understand payment events and investigate integration issues.
          PayTrace AI is an observability tool, not a payment processor.
        </p>
        <div className="health" aria-live="polite">
          <span className={`indicator ${health ? "online" : error ? "offline" : ""}`} />
          <strong>Backend health</strong>
          <span>
            {health ? health.status : error ? "Unavailable" : "Checking…"}
          </span>
        </div>
        {health && (
          <details>
            <summary>Configuration presence (values are never shown)</summary>
            <ul>
              {Object.entries(health.config_present).map(([name, present]) => (
                <li key={name}>
                  <span>{name.replaceAll("_", " ")}</span>
                  <strong>{present ? "Present" : "Missing"}</strong>
                </li>
              ))}
            </ul>
          </details>
        )}
        {error && <p className="error">{error}</p>}
      </section>
    </main>
  );
}
