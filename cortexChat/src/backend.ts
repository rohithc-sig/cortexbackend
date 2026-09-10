export type BackendEnvironment = "development" | "production";

// Change to "development" only when testing against the local FastAPI server.
const BACKEND_ENVIRONMENT: BackendEnvironment = "production";

const BACKEND_URLS: Record<BackendEnvironment, string> = {
    development: "http://localhost:8000",
    // production: "https://cortexbackend.onrender.com"
    production: "https://cortex-backend-poc-ccd5g2e4evbxgafp.canadacentral-01.azurewebsites.net"
};

export const CHAT_ENDPOINT =
    `${BACKEND_URLS[BACKEND_ENVIRONMENT]}/chat`;

export const RCA_ENDPOINT =
    `${BACKEND_URLS[BACKEND_ENVIRONMENT]}/rca`;