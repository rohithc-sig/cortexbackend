import powerbi from "powerbi-visuals-api";
import { CHAT_ENDPOINT } from "./backend";
import { BRANDING } from "./branding";

type VisualHost = powerbi.extensibility.visual.IVisualHost;

export class App {
    private container: HTMLElement;
    private host: VisualHost;
    private pbiContext: any = { categories: [] };
    private userEmail?: string;
    private rlsColumn?: string;
    private rlsValue?: string;


    private userIdentity: {
        status: "available" | "unavailable";
        userId?: string;
        tenantId?: string;
        error?: string;
    } = { status: "unavailable" };

    private interactionStarted: boolean = false;

    constructor(container: HTMLElement, host: VisualHost) {
        this.container = container;
        this.host = host;
        this.renderBaseUI();
        this.loadUserIdentity();
    }

    private async loadUserIdentity(): Promise<void> {
        try {
            const result =
                await this.host.acquireAADTokenService.acquireAADToken();

            this.userIdentity = {
                status: "available",
                userId: result.userInfo?.userId,
                tenantId: result.userInfo?.tenantId
            };
        } catch (error: any) {
            this.userIdentity = {
                status: "unavailable",
                error: error?.message || "Identity unavailable"
            };
        }
    }

    public setContext(context: any) {
        this.pbiContext = context;
    }

    public setUserEmail(userEmail?: string) {
        this.userEmail = userEmail;
    }

    public setRlsFilter(rlsColumn?: string, rlsValue?: string) {
        this.rlsColumn = rlsColumn;
        this.rlsValue = rlsValue;
    }


    // ============================================================
    // BRANDING HELPERS
    // ============================================================

    private getBrandingValue(
        value: any,
        fallback: string
    ): string {
        if (
            typeof value === "string" &&
            value.trim().length > 0
        ) {
            return value.trim();
        }

        return fallback;
    }

    private getSafeColor(
        value: any,
        fallback: string
    ): string {
        const color =
            typeof value === "string"
                ? value.trim()
                : "";

        /*
         * Branding colors are expected to come from the
         * Streamlit color picker.
         *
         * Only allow normal hex colors here so that a bad
         * branding value cannot inject CSS.
         */
        if (
            /^#[0-9A-Fa-f]{6}$/.test(color) ||
            /^#[0-9A-Fa-f]{3}$/.test(color)
        ) {
            return color;
        }

        return fallback;
    }

    private getLogoMarkup(): string {
        const logoDataUri =
            typeof BRANDING.logoDataUri === "string"
                ? BRANDING.logoDataUri.trim()
                : "";

        if (!logoDataUri) {
            return "✦";
        }

        /*
         * Only allow image data URIs.
         *
         * Streamlit will generate this from the uploaded
         * customer logo.
         */
        if (
            !/^data:image\/(png|jpeg|jpg);base64,[A-Za-z0-9+/=]+$/i.test(
                logoDataUri
            )
        ) {
            return "✦";
        }

        return `
            <img
                src="${this.escapeHtml(logoDataUri)}"
                alt="${this.escapeHtml(
                    this.getBrandingValue(
                        BRANDING.companyName,
                        "Company"
                    )
                )}"
                style="
                    width: 100%;
                    height: 100%;
                    object-fit: contain;
                    border-radius: 50%;
                "
            />
        `;
    }

    // ============================================================
    // BASE UI
    // ============================================================

    private renderBaseUI() {
        const companyName =
            this.escapeHtml(
                this.getBrandingValue(
                    BRANDING.companyName,
                    "Your Company"
                )
            );

        const headerText =
            this.escapeHtml(
                this.getBrandingValue(
                    BRANDING.headerText,
                    "AI Assistant"
                )
            );

        const assistantName =
            this.escapeHtml(
                this.getBrandingValue(
                    BRANDING.assistantName,
                    "Cortex Analyst"
                )
            );

        const welcomeMessage =
            this.escapeHtml(
                this.getBrandingValue(
                    BRANDING.welcomeMessage,
                    "How can I help you today?"
                )
            );

        const primaryColor =
            this.getSafeColor(
                BRANDING.primaryColor,
                "#0284c7"
            );

        const secondaryColor =
            this.getSafeColor(
                BRANDING.secondaryColor,
                "#14B8A6"
            );

        const logoMarkup =
            this.getLogoMarkup();

        this.container.innerHTML = `
            <style>

                :root {
                    --brand-primary: ${primaryColor};
                    --brand-secondary: ${secondaryColor};
                }

                .cortex-container {
                    font-family:
                        -apple-system,
                        BlinkMacSystemFont,
                        "Segoe UI",
                        Roboto,
                        Helvetica,
                        Arial,
                        sans-serif;

                    background-color: #ffffff;
                    height: 100%;
                    display: flex;
                    flex-direction: column;
                    box-sizing: border-box;
                    color: #1e293b;
                    overflow: hidden;
                    position: relative;
                }

                .cortex-header {
                    padding: 12px 16px;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    border-bottom: 1px solid #f1f5f9;
                    flex-shrink: 0;
                }

                .header-left {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }

                .cortex-logo {
                    width: 32px;
                    height: 32px;
                    background-color: var(--brand-primary);
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: white;
                    font-weight: bold;
                    font-size: 16px;
                    flex-shrink: 0;
                    overflow: hidden;
                }

                .header-title-container {
                    display: flex;
                    flex-direction: column;
                }

                .header-title {
                    font-weight: 700;
                    font-size: 14px;
                    color: #0f172a;
                    margin: 0;
                }

                .header-subtitle {
                    font-size: 11px;
                    color: #64748b;
                    margin: 0;
                }

                .header-right {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }

                .status-badge {
                    background-color: #dcfce7;
                    color: #15803d;
                    font-size: 11px;
                    padding: 4px 10px;
                    border-radius: 12px;
                    font-weight: 600;
                    display: flex;
                    align-items: center;
                    gap: 5px;
                }

                .status-dot {
                    width: 6px;
                    height: 6px;
                    background-color: #16a34a;
                    border-radius: 50%;
                }

                .back-btn {
                    border: 1px solid #cbd5e1;
                    background-color: #ffffff;
                    color: #475569;
                    border-radius: 6px;
                    padding: 5px 9px;
                    font-size: 10px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: all 0.15s ease;
                }

                .back-btn:hover {
                    background-color: #f8fafc;
                    border-color: #94a3b8;
                }

                .context-section {
                    padding: 8px 16px;
                    border-bottom: 1px solid #f1f5f9;
                    flex-shrink: 0;
                }

                .context-title {
                    font-size: 9px;
                    font-weight: 700;
                    color: #64748b;
                    letter-spacing: 0.5px;
                    text-transform: uppercase;
                    margin-bottom: 6px;
                }

                .chips-container {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 6px;
                }

                .chip {
                    background-color: #f8fafc;
                    border: 1px solid #e2e8f0;
                    border-radius: 14px;
                    padding: 3px 8px;
                    font-size: 11px;
                    color: #475569;
                    display: flex;
                    align-items: center;
                    gap: 4px;
                }

                .chip-brand {
                    color: var(--brand-primary);
                    font-weight: 700;
                }

                .welcome-screen {
                    flex-grow: 1;
                    overflow-y: auto;
                    padding: 24px 18px 18px 18px;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    box-sizing: border-box;
                }

                .welcome-icon {
                    width: 46px;
                    height: 46px;
                    border-radius: 50%;
                    background-color: var(--brand-primary);
                    color: white;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 22px;
                    font-weight: 700;
                    margin-bottom: 12px;
                    overflow: hidden;
                }

                .welcome-title {
                    font-size: 19px;
                    font-weight: 700;
                    color: #0f172a;
                    margin: 0;
                    text-align: center;
                }

                .welcome-subtitle {
                    font-size: 12px;
                    line-height: 1.5;
                    color: #64748b;
                    margin: 7px 0 20px 0;
                    text-align: center;
                    max-width: 420px;
                }

                .company-label {
                    font-size: 10px;
                    font-weight: 700;
                    color: var(--brand-secondary);
                    margin-top: -8px;
                    margin-bottom: 16px;
                    text-align: center;
                }

                .starter-section {
                    width: 100%;
                    max-width: 520px;
                }

                .starter-title {
                    font-size: 9px;
                    font-weight: 700;
                    color: #64748b;
                    letter-spacing: 0.5px;
                    text-transform: uppercase;
                    margin-bottom: 8px;
                }

                .starter-questions {
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                }

                .starter-question {
                    width: 100%;
                    box-sizing: border-box;
                    border: 1px solid var(--brand-primary);
                    background-color: #f8fbff;
                    color: var(--brand-primary);
                    border-radius: 9px;
                    padding: 10px 12px;
                    font-size: 11px;
                    text-align: left;
                    cursor: pointer;
                    transition: all 0.15s ease;
                }

                .starter-question:hover {
                    background-color: #eff6ff;
                    border-color: var(--brand-primary);
                    transform: translateY(-1px);
                }

                .custom-question-hint {
                    margin-top: 12px;
                    width: 100%;
                    max-width: 520px;
                    box-sizing: border-box;
                    padding: 9px 12px;
                    border-radius: 8px;
                    background-color: #f8fafc;
                    border: 1px solid #e2e8f0;
                    color: #64748b;
                    font-size: 10px;
                    text-align: center;
                }

                .custom-question-hint strong {
                    color: var(--brand-primary);
                }

                .request-debug-section {
                    margin: 6px 12px;
                    border: 1px solid var(--brand-primary);
                    background-color: #eff6ff;
                    border-radius: 6px;
                    padding: 6px 8px;
                    box-sizing: border-box;
                    flex-shrink: 0;
                }

                .request-debug-header-row {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 8px;
                    width: 100%;
                }

                .request-debug-title {
                    font-size: 9px;
                    font-weight: 700;
                    color: var(--brand-primary);
                    letter-spacing: 0.5px;
                    text-transform: uppercase;
                }

                .request-debug-actions {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                }

                .request-debug-toggle {
                    border: 1px solid var(--brand-primary);
                    background-color: #ffffff;
                    color: var(--brand-primary);
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 9px;
                    font-weight: 700;
                    cursor: pointer;
                }

                .copy-request-btn {
                    display: block !important;
                    visibility: visible !important;
                    opacity: 1 !important;
                    border: 1px solid var(--brand-primary);
                    background-color: #ffffff;
                    color: var(--brand-primary);
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-size: 10px;
                    font-weight: 600;
                    cursor: pointer;
                    min-width: 55px;
                    height: 24px;
                    z-index: 9999;
                }

                .copy-request-btn:hover {
                    background-color: #dbeafe;
                }

                .copy-request-btn.copied {
                    color: #15803d;
                    border-color: #86efac;
                    background-color: #f0fdf4;
                }

                .request-debug-content {
                    margin: 0;
                    color: var(--brand-primary);
                    font-family:
                        Consolas,
                        "Courier New",
                        monospace;
                    font-size: 9px;
                    line-height: 1.3;
                    white-space: pre-wrap;
                    word-break: break-word;
                    max-height: 100px;
                    overflow-y: auto;
                }

                .toast-container {
                    position: absolute;
                    right: 12px;
                    bottom: 12px;
                    z-index: 99999;
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                    pointer-events: none;
                }

                .toast,
                .toast-notification {
                    min-width: 190px;
                    max-width: 280px;
                    padding: 10px 14px;
                    border-radius: 8px;
                    font-size: 11px;
                    font-weight: 600;
                    box-shadow:
                        0 10px 25px -5px rgba(
                            15,
                            23,
                            42,
                            0.12
                        ),
                        0 8px 10px -6px rgba(
                            15,
                            23,
                            42,
                            0.08
                        );
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 8px;
                    pointer-events: auto;
                    animation:
                        toast-notification-in
                        0.25s
                        cubic-bezier(
                            0.16,
                            1,
                            0.3,
                            1
                        )
                        forwards;
                    transition: all 0.2s ease;
                }

                .toast-success,
                .toast-notification-success {
                    border: 1px solid #86efac;
                    background-color: #f0fdf4;
                    color: #166534;
                }

                .toast-error,
                .toast-notification-error {
                    border: 1px solid #fca5a5;
                    background-color: #fef2f2;
                    color: #991b1b;
                }

                .toast-info,
                .toast-notification-info {
                    border: 1px solid var(--brand-primary);
                    background-color: #eff6ff;
                    color: var(--brand-primary);
                }

                .toast-notification-fade-out {
                    animation:
                        toast-notification-out
                        0.2s
                        cubic-bezier(
                            0.7,
                            0,
                            0.84,
                            0
                        )
                        forwards;
                }

                @keyframes toast-notification-in {
                    from {
                        opacity: 0;
                        transform:
                            translateY(10px)
                            scale(0.96);
                    }

                    to {
                        opacity: 1;
                        transform:
                            translateY(0)
                            scale(1);
                    }
                }

                @keyframes toast-notification-out {
                    from {
                        opacity: 1;
                        transform:
                            translateY(0)
                            scale(1);
                    }

                    to {
                        opacity: 0;
                        transform:
                            translateY(10px)
                            scale(0.96);
                    }
                }

                .chat-history {
                    flex-grow: 1;
                    overflow-y: auto;
                    padding: 16px;
                    display: flex;
                    flex-direction: column;
                    gap: 16px;
                }

                .user-message {
                    align-self: flex-end;
                    background-color: var(--brand-primary);
                    color: white;
                    padding: 10px 16px;
                    border-radius:
                        18px
                        18px
                        2px
                        18px;
                    font-size: 13px;
                    max-width: 85%;
                }

                .bot-message-header {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    font-size: 12px;
                    font-weight: 600;
                    color: #475569;
                    margin-bottom: 6px;
                }

                .bot-avatar {
                    width: 20px;
                    height: 20px;
                    background-color: var(--brand-primary);
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: white;
                    font-size: 10px;
                    overflow: hidden;
                }

                .bot-content {
                    font-size: 13px;
                    line-height: 1.5;
                    color: #334155;
                }

                .data-table-wrapper {
                    border: 1px solid #cbd5e1;
                    border-radius: 8px;
                    overflow-x: auto;
                    max-height: 300px;
                    overflow-y: auto;
                    margin-top: 10px;
                    box-shadow:
                        0 1px 2px
                        rgba(
                            0,
                            0,
                            0,
                            0.03
                        );
                }

                .data-table {
                    width: 100%;
                    border-collapse: separate;
                    border-spacing: 0;
                    font-size: 12px;
                }

                .data-table th {
                    position: sticky;
                    top: 0;
                    z-index: 10;
                    text-align: left;
                    padding: 8px 10px;
                    background-color: #f8fafc;
                    color: #64748b;
                    font-weight: 600;
                    border-bottom:
                        1px solid
                        #e2e8f0;
                    text-transform: uppercase;
                    font-size: 10px;
                    box-shadow:
                        0 1px 0
                        #e2e8f0;
                }

                .data-table td {
                    padding: 8px 10px;
                    border-bottom:
                        1px solid
                        #f1f5f9;
                    color: #1e293b;
                }

                .data-table tbody tr {
                    background-color: #ffffff;
                    transition:
                        background-color
                        0.16s ease,
                        box-shadow
                        0.16s ease;
                }

                .data-table tbody tr:nth-child(even) {
                    background-color: #f5f5f5;
                }

                .data-table tbody tr:hover {
                    background-color: #eaf3ff;
                    box-shadow:
                        inset 0 0 0 1px
                        #d0e4ff;
                }

                .kpi-cards-container {
                    display: grid;
                    grid-template-columns:
                        repeat(
                            auto-fit,
                            minmax(
                                130px,
                                1fr
                            )
                        );
                    gap: 10px;
                    margin: 12px 0;
                }

                .kpi-card {
                    background: #ffffff;
                    border:
                        1px solid
                        #e2e8f0;
                    border-radius: 8px;
                    padding: 10px 12px;
                    box-shadow:
                        0 1px 3px
                        rgba(
                            0,
                            0,
                            0,
                            0.04
                        );
                    display: flex;
                    flex-direction: column;
                    gap: 4px;
                }

                .kpi-title {
                    font-size: 10px;
                    font-weight: 700;
                    color: #64748b;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                }

                .kpi-value {
                    font-size: 18px;
                    font-weight: 700;
                    color: #0f172a;
                    line-height: 1.2;
                }

                .kpi-subtext {
                    font-size: 10px;
                    color: #94a3b8;
                    display: flex;
                    align-items: center;
                    gap: 4px;
                }

                .kpi-badge {
                    display: inline-flex;
                    align-items: center;
                    padding: 2px 6px;
                    border-radius: 12px;
                    font-size: 10px;
                    font-weight: 600;
                }

                .kpi-badge-success {
                    background-color: #dcfce7;
                    color: #15803d;
                }

                .kpi-badge-danger {
                    background-color: #fee2e2;
                    color: #991b1b;
                }

                .download-csv-btn,
                .copy-csv-btn,
                .copy-sql-btn {
                    margin-top: 8px;
                    border:
                        1px solid
                        #cbd5e1;
                    background-color: #ffffff;
                    color: #334155;
                    border-radius: 6px;
                    padding: 6px 10px;
                    font-size: 11px;
                    font-weight: 600;
                    cursor: pointer;
                }

                .download-csv-btn:hover,
                .copy-csv-btn:hover,
                .copy-sql-btn:hover {
                    background-color: #f8fafc;
                    border-color:
                        var(--brand-primary);
                    color:
                        var(--brand-primary);
                }

                .copy-csv-btn {
                    margin-left: 8px;
                }

                .rca-section {
                    margin-top: 12px;
                    border:
                        1px solid
                        var(--brand-primary);
                    background-color: #f8fbff;
                    border-radius: 10px;
                    padding: 12px;
                }

                .rca-title {
                    font-size: 11px;
                    font-weight: 800;
                    color: var(--brand-secondary);
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                    margin-bottom: 10px;
                }

                .rca-summary {
                    font-size: 12px;
                    line-height: 1.55;
                    color: #334155;
                    margin-bottom: 12px;
                }

                .rca-subtitle {
                    font-size: 10px;
                    font-weight: 800;
                    color: #475569;
                    text-transform: uppercase;
                    letter-spacing: 0.45px;
                    margin: 12px 0 7px 0;
                }

                .rca-driver {
                    border:
                        1px solid
                        #e2e8f0;
                    background: #ffffff;
                    border-radius: 8px;
                    padding: 9px;
                    margin-bottom: 7px;
                }

                .rca-driver-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: flex-start;
                    gap: 8px;
                    margin-bottom: 5px;
                }

                .rca-driver-name {
                    font-size: 11px;
                    font-weight: 700;
                    color: #0f172a;
                }

                .rca-confidence {
                    flex-shrink: 0;
                    border-radius: 10px;
                    padding: 2px 7px;
                    font-size: 9px;
                    font-weight: 700;
                }

                .rca-confidence-high {
                    background-color: #dcfce7;
                    color: #166534;
                }

                .rca-confidence-medium {
                    background-color: #fef3c7;
                    color: #92400e;
                }

                .rca-confidence-low {
                    background-color: #fee2e2;
                    color: #991b1b;
                }

                .rca-driver-row {
                    margin-top: 4px;
                    font-size: 10px;
                    line-height: 1.45;
                    color: #475569;
                }

                .rca-driver-label {
                    font-weight: 700;
                    color: #334155;
                }

                .rca-list {
                    margin: 0;
                    padding-left: 18px;
                }

                .rca-list li {
                    font-size: 11px;
                    line-height: 1.5;
                    color: #475569;
                    margin-bottom: 5px;
                }

                .rca-caveat {
                    font-size: 10px;
                    line-height: 1.45;
                    color: #64748b;
                    margin-top: 5px;
                    padding: 7px 9px;
                    border-left:
                        3px solid
                        var(--brand-secondary);
                    background: #ffffff;
                }

                .sql-accordion {
                    margin-top: 10px;
                    border:
                        1px solid
                        #e2e8f0;
                    border-radius: 20px;
                    padding: 6px 12px;
                    font-size: 12px;
                    color: #334155;
                    cursor: pointer;
                }

                .follow-up-section {
                    margin-top: 12px;
                    border:
                        1px solid
                        var(--brand-primary);
                    background-color: #f8fbff;
                    border-radius: 12px;
                    padding: 10px 12px;
                }

                .follow-up-title {
                    font-size: 9px;
                    font-weight: 700;
                    color: var(--brand-primary);
                    letter-spacing: 0.5px;
                    text-transform: uppercase;
                    margin-bottom: 8px;
                }

                .follow-up-list {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 8px;
                }

                .follow-up-chip {
                    background-color: #ffffff;
                    border:
                        1px solid
                        var(--brand-primary);
                    border-radius: 999px;
                    padding: 6px 10px;
                    font-size: 11px;
                    color: var(--brand-primary);
                    cursor: pointer;
                    transition: all 0.15s ease;
                }

                .follow-up-chip:hover {
                    background-color: #eff6ff;
                }

                .input-container {
                    padding: 8px 16px 12px 16px;
                    position: relative;
                    flex-shrink: 0;
                    background-color: #ffffff;
                }

                .input-box {
                    width: 100%;
                    padding:
                        10px
                        42px
                        10px
                        14px;
                    border:
                        1px solid
                        #cbd5e1;
                    border-radius: 24px;
                    outline: none;
                    font-size: 12px;
                    box-sizing: border-box;
                }

                .input-box:focus {
                    border-color:
                        var(--brand-primary);
                    box-shadow:
                        0 0 0 2px
                        #eff6ff;
                }

                .send-btn {
                    position: absolute;
                    right: 22px;
                    top: 50%;
                    transform:
                        translateY(-50%);
                    width: 28px;
                    height: 28px;
                    background-color:
                        var(--brand-primary);
                    border: none;
                    border-radius: 50%;
                    color: white;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    cursor: pointer;
                }

                .send-btn:hover {
                    opacity: 0.85;
                }

            </style>

            <div class="cortex-container">

                <div class="cortex-header">

                    <div class="header-left">

                        <div class="cortex-logo">
                            ${logoMarkup}
                        </div>

                        <div class="header-title-container">

                            <h3 class="header-title">
                                ${headerText}
                            </h3>

                            <p class="header-subtitle">
                                ${companyName}
                                · Custom Power BI visual
                            </p>

                        </div>

                    </div>

                    <div class="header-right">

                        <button
                            id="backBtn"
                            class="back-btn"
                            type="button"
                            style="display: none;"
                        >
                            ← Back
                        </button>

                        <div class="status-badge">

                            <span class="status-dot"></span>

                            Connected

                        </div>

                    </div>

                </div>

                <div class="context-section">

                    <div class="context-title">
                        ASSISTANT HAS ACCESS TO
                    </div>

                    <div class="chips-container">

                        <div class="chip">
                            <span class="chip-brand">Y</span>
                            Current report filters
                        </div>

                        <div class="chip">
                            <span class="chip-brand">✦</span>
                            Selected visuals
                        </div>

                        <div class="chip">
                            <span class="chip-brand">☵</span>
                            Current page context
                        </div>

                        <div class="chip">
                            <span class="chip-brand">⛁</span>
                            Semantic model
                        </div>

                        <div class="chip">
                            <span class="chip-brand">⛁</span>
                            Snowflake Cortex Analyst
                        </div>

                    </div>

                </div>

                <div
                    id="welcomeScreen"
                    class="welcome-screen"
                >

                    <div class="welcome-icon">
                        ${logoMarkup}
                    </div>

                    <h2 class="welcome-title">
                        Hello, welcome to ${assistantName}
                    </h2>

                    <div class="welcome-subtitle">
                        ${welcomeMessage}
                    </div>

                    <div class="company-label">
                        ${companyName}
                    </div>

                    <div class="starter-section">

                        <div class="starter-title">
                            GET STARTED WITH A QUESTION
                        </div>

                        <div class="starter-questions">

                            <button
                                class="starter-question"
                                type="button"
                                data-question="Top 10 brands"
                            >
                                Top 10 brands
                            </button>

                            <button
                                class="starter-question"
                                type="button"
                                data-question="Revenue by retailer"
                            >
                                Revenue by retailer
                            </button>

                            <button
                                class="starter-question"
                                type="button"
                                data-question="Sales trend over time"
                            >
                                Sales trend over time
                            </button>

                            <button
                                class="starter-question"
                                type="button"
                                data-question="Which products are declining?"
                            >
                                Which products are declining?
                            </button>

                        </div>

                    </div>

                    <div class="custom-question-hint">
                        Or ask a
                        <strong>custom question</strong>
                        using the input box below.
                    </div>

                </div>

                <div
                    id="requestDebugSection"
                    class="request-debug-section"
                    style="display: none;"
                >

                    <div class="request-debug-header-row">

                        <div class="request-debug-title">
                            REQUEST SENT BY POWER BI
                        </div>

                        <div class="request-debug-actions">

                            <button
                                class="request-debug-toggle"
                                data-action="toggle-debug"
                                type="button"
                            >
                                Show
                            </button>

                            <button
                                id="copyRequestBtn"
                                class="copy-request-btn"
                                type="button"
                            >
                                Copy
                            </button>

                        </div>

                    </div>

                    <pre
                        id="requestDebugContent"
                        class="request-debug-content"
                        hidden
                    >{
  "question": "",
  "pbi_context": {
    "categories": []
  }
}</pre>

                </div>

                <div
                    id="cortexToast"
                    class="toast-container"
                    aria-live="polite"
                    aria-atomic="true"
                ></div>

                <div
                    class="chat-history"
                    id="chatHistory"
                    style="display: none;"
                ></div>

                <div class="input-container">

                    <input
                        type="text"
                        id="cortexQueryInput"
                        class="input-box"
                        placeholder="Ask about this report..."
                    />

                    <button
                        id="cortexAskBtn"
                        class="send-btn"
                        type="button"
                    >
                        ➔
                    </button>

                </div>

            </div>
        `;

        this.attachEvents();
    }

    // ============================================================
    // EVENTS
    // ============================================================

    private attachEvents() {

        const askBtn =
            this.container.querySelector(
                "#cortexAskBtn"
            ) as HTMLButtonElement;

        const queryInput =
            this.container.querySelector(
                "#cortexQueryInput"
            ) as HTMLInputElement;

        const backBtn =
            this.container.querySelector(
                "#backBtn"
            ) as HTMLButtonElement;

        const triggerQuery = () => {

            const queryText =
                queryInput.value.trim();

            if (queryText) {

                this.startInteraction();

                this.handleAskQuery(
                    queryText
                );

                queryInput.value = "";
            }
        };

        askBtn.addEventListener(
            "click",
            triggerQuery
        );

        queryInput.addEventListener(
            "keypress",
            (e) => {

                if (e.key === "Enter") {
                    triggerQuery();
                }

            }
        );

        const starterQuestions =
            this.container.querySelectorAll(
                ".starter-question"
            );

        starterQuestions.forEach(
            button => {

                button.addEventListener(
                    "click",
                    () => {

                        const question =
                            (
                                button as HTMLElement
                            ).dataset.question || "";

                        if (!question) {
                            return;
                        }

                        this.startInteraction();

                        this.handleAskQuery(
                            question
                        );

                    }
                );

            }
        );

        if (backBtn) {

            backBtn.addEventListener(
                "click",
                () => {
                    this.returnToWelcome();
                }
            );

        }

        const copyRequestBtn =
            this.container.querySelector(
                "#copyRequestBtn"
            ) as HTMLButtonElement;

        const debugToggleBtn =
            this.container.querySelector(
                "[data-action='toggle-debug']"
            ) as HTMLButtonElement;

        const debugContent =
            this.container.querySelector(
                "#requestDebugContent"
            ) as HTMLElement;

        if (debugToggleBtn && debugContent) {

            debugToggleBtn.addEventListener(
                "click",
                () => {

                    const isHidden =
                        debugContent.hidden;

                    debugContent.hidden =
                        !isHidden;

                    debugToggleBtn.textContent =
                        isHidden ? "Hide" : "Show";

                }
            );

        }

        if (copyRequestBtn) {

            copyRequestBtn.addEventListener(
                "click",
                async (event) => {

                    event.preventDefault();
                    event.stopPropagation();

                    const textToCopy =
                        debugContent?.textContent || "";

                    const copied =
                        await this.copyTextToClipboard(
                            textToCopy
                        );

                    if (copied) {

                        copyRequestBtn.textContent =
                            "Copied!";

                        copyRequestBtn.classList.add(
                            "copied"
                        );

                        this.showToast(
                            "Power BI request copied",
                            "success"
                        );

                        setTimeout(
                            () => {

                                copyRequestBtn.textContent =
                                    "Copy";

                                copyRequestBtn.classList.remove(
                                    "copied"
                                );

                            },
                            1500
                        );

                    } else {

                        this.showToast(
                            "Unable to copy Power BI request",
                            "error"
                        );

                    }

                }
            );

        }

        this.container.addEventListener(
            "click",
            async (event) => {

                const target =
                    event.target as HTMLElement;

                const downloadButton =
                    target.closest(
                        '[data-action="download-csv"]'
                    ) as HTMLButtonElement;

                if (downloadButton) {

                    event.preventDefault();
                    event.stopPropagation();

                    const botContent =
                        downloadButton.closest(
                            ".bot-content"
                        ) as HTMLElement;

                    if (!botContent) {
                        return;
                    }

                    const csvData =
                        (botContent as any).__csvData;

                    if (
                        !csvData ||
                        !csvData.columns ||
                        !csvData.rows
                    ) {

                        this.showToast(
                            "CSV data not found",
                            "error"
                        );

                        return;
                    }

                    const originalButtonText =
                        downloadButton.textContent ||
                        "Download CSV";

                    downloadButton.disabled =
                        true;

                    downloadButton.textContent =
                        "Downloading...";

                    try {

                        await this.downloadCsv(
                            csvData.columns,
                            csvData.rows
                        );

                    } finally {

                        setTimeout(
                            () => {

                                downloadButton.disabled =
                                    false;

                                downloadButton.textContent =
                                    originalButtonText;

                            },
                            1200
                        );

                    }

                    return;
                }

                const copyCsvButton =
                    target.closest(
                        '[data-action="copy-csv"]'
                    ) as HTMLButtonElement;

                if (copyCsvButton) {

                    event.preventDefault();
                    event.stopPropagation();

                    const botContent =
                        copyCsvButton.closest(
                            ".bot-content"
                        ) as HTMLElement;

                    if (!botContent) {
                        return;
                    }

                    const csvData =
                        (botContent as any).__csvData;

                    const csvText =
                        csvData && csvData.csvText
                            ? csvData.csvText
                            : this.buildCsvContent(
                                  csvData?.columns || [],
                                  csvData?.rows || []
                              );

                    const originalButtonText =
                        copyCsvButton.textContent ||
                        "Copy CSV";

                    copyCsvButton.disabled =
                        true;

                    copyCsvButton.textContent =
                        "Copying...";

                    const copied =
                        await this.copyTextToClipboard(
                            csvText
                        );

                    copyCsvButton.disabled =
                        false;

                    if (copied) {

                        copyCsvButton.textContent =
                            "Copied!";

                        this.showToast(
                            "CSV copied to clipboard",
                            "success"
                        );

                    } else {

                        copyCsvButton.textContent =
                            originalButtonText;

                        this.showToast(
                            "Unable to copy CSV. Please try again.",
                            "error"
                        );

                    }

                    setTimeout(
                        () => {

                            copyCsvButton.textContent =
                                originalButtonText;

                        },
                        1200
                    );

                    return;
                }

                const followUpButton =
                    target.closest(
                        '[data-action="follow-up-question"]'
                    ) as HTMLButtonElement;

                if (followUpButton) {

                    event.preventDefault();
                    event.stopPropagation();

                    const inputEl =
                        this.container.querySelector(
                            "#cortexQueryInput"
                        ) as HTMLInputElement | null;

                    if (inputEl) {

                        inputEl.value =
                            followUpButton.dataset.question || "";

                        inputEl.focus();

                    }

                    return;
                }

                const copySqlButton =
                    target.closest(
                        '[data-action="copy-sql"]'
                    ) as HTMLButtonElement;

                if (copySqlButton) {

                    event.preventDefault();
                    event.stopPropagation();

                    const botContent =
                        copySqlButton.closest(
                            ".bot-content"
                        ) as HTMLElement;

                    if (!botContent) {
                        return;
                    }

                    const sqlText =
                        (botContent as any).__sqlText || "";

                    const originalButtonText =
                        copySqlButton.textContent ||
                        "Copy SQL";

                    copySqlButton.disabled =
                        true;

                    copySqlButton.textContent =
                        "Copying...";

                    const copied =
                        await this.copyTextToClipboard(
                            sqlText
                        );

                    copySqlButton.disabled =
                        false;

                    if (copied) {

                        copySqlButton.textContent =
                            "Copied!";

                        this.showToast(
                            "SQL copied to clipboard",
                            "success"
                        );

                    } else {

                        copySqlButton.textContent =
                            originalButtonText;

                        this.showToast(
                            "Unable to copy SQL. Please try again.",
                            "error"
                        );

                    }

                    setTimeout(
                        () => {

                            copySqlButton.textContent =
                                originalButtonText;

                        },
                        1200
                    );

                }

            }
        );

    }

    // ============================================================
    // INTERACTION STATE
    // ============================================================

    private startInteraction() {

        if (this.interactionStarted) {
            return;
        }

        this.interactionStarted =
            true;

        const welcomeScreen =
            this.container.querySelector(
                "#welcomeScreen"
            ) as HTMLElement;

        const chatHistory =
            this.container.querySelector(
                "#chatHistory"
            ) as HTMLElement;

        const backBtn =
            this.container.querySelector(
                "#backBtn"
            ) as HTMLButtonElement;

        const debugSection =
            this.container.querySelector(
                "#requestDebugSection"
            ) as HTMLElement;

        if (welcomeScreen) {
            welcomeScreen.style.display = "none";
        }

        if (chatHistory) {
            chatHistory.style.display = "flex";
        }

        if (backBtn) {
            backBtn.style.display = "block";
        }

        if (debugSection) {
            debugSection.style.display = "block";
        }

    }

    private returnToWelcome() {

        this.interactionStarted =
            false;

        const welcomeScreen =
            this.container.querySelector(
                "#welcomeScreen"
            ) as HTMLElement;

        const chatHistory =
            this.container.querySelector(
                "#chatHistory"
            ) as HTMLElement;

        const backBtn =
            this.container.querySelector(
                "#backBtn"
            ) as HTMLButtonElement;

        const debugSection =
            this.container.querySelector(
                "#requestDebugSection"
            ) as HTMLElement;

        const debugContent =
            this.container.querySelector(
                "#requestDebugContent"
            ) as HTMLElement;

        const debugToggle =
            this.container.querySelector(
                "[data-action='toggle-debug']"
            ) as HTMLButtonElement;

        const queryInput =
            this.container.querySelector(
                "#cortexQueryInput"
            ) as HTMLInputElement;

        if (chatHistory) {

            chatHistory.innerHTML = "";
            chatHistory.style.display = "none";

        }

        if (welcomeScreen) {
            welcomeScreen.style.display = "flex";
        }

        if (backBtn) {
            backBtn.style.display = "none";
        }

        if (debugSection) {
            debugSection.style.display = "none";
        }

        if (debugContent) {

            debugContent.textContent = `{
  "question": "",
  "pbi_context": {
    "categories": []
  }
}`;

            debugContent.hidden = true;

        }

        if (debugToggle) {
            debugToggle.textContent = "Show";
        }

        if (queryInput) {

            queryInput.value = "";
            queryInput.focus();

        }

    }

    // ============================================================
    // CHAT REQUEST
    // ============================================================

    private async handleAskQuery(
        queryText: string
    ) {

        const chatHistory =
            this.container.querySelector(
                "#chatHistory"
            ) as HTMLElement;

        await this.loadUserIdentity();

        const requestPayload = {

            question:
                queryText,

            pbi_context:
                this.pbiContext,

            user_email:
                this.userEmail,

            rls_column:
                this.rlsColumn,

            rls_values:
                this.rlsValue !== undefined ? [this.rlsValue] : undefined,


            user_identity:
                this.userIdentity

        };

        const requestDebugContent =
            this.container.querySelector(
                "#requestDebugContent"
            ) as HTMLElement;

        if (requestDebugContent) {

            requestDebugContent.textContent =
                JSON.stringify(
                    requestPayload,
                    null,
                    2
                );

        }

        const userBubble =
            document.createElement(
                "div"
            );

        userBubble.className =
            "user-message";

        userBubble.textContent =
            queryText;

        chatHistory.appendChild(
            userBubble
        );

        const assistantName =
            this.escapeHtml(
                this.getBrandingValue(
                    BRANDING.assistantName,
                    "Cortex Analyst"
                )
            );

        const logoMarkup =
            this.getLogoMarkup();

        const botBubble =
            document.createElement(
                "div"
            );

        botBubble.innerHTML = `

            <div class="bot-message-header">

                <div class="bot-avatar">
                    ${logoMarkup}
                </div>

                <span>
                    ${assistantName}
                </span>

            </div>

            <div
                class="bot-content"
                style="color: var(--brand-primary);"
            >
                Thinking...
            </div>

        `;

        chatHistory.appendChild(
            botBubble
        );

        chatHistory.scrollTop =
            chatHistory.scrollHeight;

        try {

            const response =
                await fetch(
                    CHAT_ENDPOINT,
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body:
                            JSON.stringify(
                                requestPayload
                            )
                    }
                );

            if (!response.ok) {

                const errorText =
                    await response.text();

                throw new Error(
                    `Server returned ${response.status}: ${errorText}`
                );

            }

            const data =
                await response.json();

            this.renderResponse(
                botBubble,
                data
            );

        } catch (error: any) {

            const contentDiv =
                botBubble.querySelector(
                    ".bot-content"
                ) as HTMLElement;

            if (contentDiv) {

                contentDiv.style.color =
                    "#dc2626";

                contentDiv.textContent =
                    `Error: ${error.message}`;

            }

        }

    }

    // ============================================================
    // RESPONSE RENDERING
    // ============================================================

    private renderResponse(
        botBubble: HTMLElement,
        data: any
    ) {

        const chatHistory =
            this.container.querySelector(
                "#chatHistory"
            ) as HTMLElement;

        let tableHtml = "";

        if (
            data.columns &&
            data.rows &&
            data.rows.length > 0
        ) {

            const headers =
                data.columns
                    .map(
                        (col: string) =>
                            `<th>${this.escapeHtml(col)}</th>`
                    )
                    .join("");

            const rowsHtml =
                data.rows
                    .map(
                        (
                            row: any,
                            idx: number
                        ) => {

                            const cells =
                                data.columns
                                    .map(
                                        (col: string) =>
                                            `<td>${
                                                row[col] !== undefined &&
                                                row[col] !== null
                                                    ? this.escapeHtml(
                                                          String(row[col])
                                                      )
                                                    : ""
                                            }</td>`
                                    )
                                    .join("");

                            return `
                                <tr>

                                    <td
                                        style="
                                            color: #94a3b8;
                                            font-size: 10px;
                                        "
                                    >
                                        ${idx + 1}
                                    </td>

                                    ${cells}

                                </tr>
                            `;

                        }
                    )
                    .join("");

            tableHtml = `

                <div class="data-table-wrapper">

                    <table class="data-table">

                        <thead>

                            <tr>

                                <th>
                                    #
                                </th>

                                ${headers}

                            </tr>

                        </thead>

                        <tbody>

                            ${rowsHtml}

                        </tbody>

                    </table>

                </div>

                <div>

                    <button
                        class="download-csv-btn"
                        data-action="download-csv"
                        type="button"
                    >
                        ↓ Download CSV
                    </button>

                    <button
                        class="copy-csv-btn"
                        data-action="copy-csv"
                        type="button"
                    >
                        Copy CSV
                    </button>

                </div>

            `;

        }

        const botContent =
            botBubble.querySelector(
                ".bot-content"
            ) as HTMLElement;

        if (!botContent) {
            return;
        }

        const csvText =
            this.buildCsvContent(
                data.columns || [],
                data.rows || []
            );

        (botContent as any).__csvData = {

            columns:
                data.columns || [],

            rows:
                data.rows || [],

            csvText

        };

        (botContent as any).__sqlText =
            data.sql || "";

        botContent.style.color =
            "#334155";

        const followUpQuestions =
            Array.isArray(
                data.follow_up_questions
            )
                ? data.follow_up_questions.filter(
                      (q: any) =>
                          typeof q === "string" &&
                          q.trim()
                  )
                : [];

        const followUpHtml =
            followUpQuestions.length > 0
                ? `
                    <div class="follow-up-section">

                        <div class="follow-up-title">
                            Follow-up questions
                        </div>

                        <div class="follow-up-list">

                            ${followUpQuestions
                                .map(
                                    q => `
                                        <button
                                            class="follow-up-chip"
                                            type="button"
                                            data-action="follow-up-question"
                                            data-question="${this.escapeHtml(
                                                q
                                            )}"
                                        >
                                            ${this.escapeHtml(q)}
                                        </button>
                                    `
                                )
                                .join("")}

                        </div>

                    </div>
                `
                : "";

        // ------------------------------------------------------
        // RCA rendering.
        //
        // The backend runs the entire RCA auto-flow synchronously
        // inside /chat and reports the outcome via "rca_status":
        //
        //   "not_diagnostic"        -> question wasn't diagnostic,
        //                               render nothing
        //   "insufficient_evidence" -> diagnostic, but the result
        //                               set didn't have enough
        //                               rows/columns for RCA
        //   "success"               -> data.rca is populated,
        //                               render the full section
        //   "failed"                -> RCA was attempted but the
        //                               AI_COMPLETE call errored
        //                               server-side
        //
        // No second network call is made here.
        // ------------------------------------------------------

        let rcaHtml = "";

        const rcaStatus =
            data.rca_status;

        if (rcaStatus === "success") {

            const rcaData =
                this.getRcaFromResponse(
                    data
                );

            if (rcaData) {

                rcaHtml =
                    this.buildRcaHtml(
                        rcaData
                    );

            }

        } else if (
            rcaStatus === "insufficient_evidence"
        ) {

            rcaHtml =
                this.buildRcaInsufficientHtml(
                    data.rca_evidence
                );

        } else if (
            rcaStatus === "failed"
        ) {

            rcaHtml =
                this.buildRcaFailedHtml();

        }

        botContent.innerHTML = `

            <div>
                ${data.answer || ""}
            </div>

            ${tableHtml}

            ${rcaHtml}

            ${followUpHtml}

            ${
                data.sql
                    ? `

                        <details
                            class="sql-accordion"
                        >

                            <summary
                                style="
                                    font-weight: 600;
                                    cursor: pointer;
                                "
                            >
                                › Generated SQL
                            </summary>

                            <div
                                style="
                                    display: flex;
                                    justify-content: flex-end;
                                    margin-top: 8px;
                                "
                            >

                                <button
                                    class="copy-sql-btn"
                                    data-action="copy-sql"
                                    type="button"
                                >
                                    Copy SQL
                                </button>

                            </div>

                            <pre
                                style="
                                    background: #1e293b;
                                    color: #f8fafc;
                                    padding: 10px;
                                    border-radius: 6px;
                                    overflow-x: auto;
                                    font-size: 11px;
                                    margin-top: 6px;
                                "
                            ><code>${this.escapeHtml(
                                data.sql
                            )}</code></pre>

                        </details>

                    `
                    : ""
            }

        `;

        chatHistory.scrollTop =
            chatHistory.scrollHeight;

        (botContent as any).__csvData = {

            columns:
                data.columns || [],

            rows:
                data.rows || [],

            csvText

        };

        (botContent as any).__sqlText =
            data.sql || "";

    }

    // ============================================================
    // RCA
    // ============================================================

    private getRcaFromResponse(
        data: any
    ): any | null {

        if (
            data &&
            data.rca &&
            typeof data.rca === "object"
        ) {

            return data.rca;

        }

        if (
            data &&
            data.rca_result &&
            typeof data.rca_result === "object"
        ) {

            return data.rca_result;

        }

        if (
            data &&
            data.diagnostic_result &&
            typeof data.diagnostic_result === "object" &&
            data.diagnostic_result.rca
        ) {

            return data.diagnostic_result.rca;

        }

        return null;

    }

    private buildRcaHtml(
        data: any
    ): string {

        const summary =
            typeof data.summary === "string"
                ? data.summary
                : "";

        const primaryDrivers =
            Array.isArray(
                data.primary_drivers
            )
                ? data.primary_drivers
                : [];

        const secondaryDrivers =
            Array.isArray(
                data.secondary_drivers
            )
                ? data.secondary_drivers
                : [];

        const recommendations =
            Array.isArray(
                data.recommendations
            )
                ? data.recommendations
                : [];

        const confidenceCaveats =
            Array.isArray(
                data.confidence_caveats
            )
                ? data.confidence_caveats
                : [];

        return `

            <div class="rca-section">

                <div class="rca-title">
                    ✦ Root Cause Analysis
                </div>

                ${
                    summary
                        ? `
                            <div class="rca-summary">
                                ${this.escapeHtml(summary)}
                            </div>
                        `
                        : ""
                }

                ${
                    primaryDrivers.length > 0
                        ? `
                            <div class="rca-subtitle">
                                Primary Drivers
                            </div>

                            ${primaryDrivers
                                .map(
                                    (driver: any) =>
                                        this.renderRcaDriver(
                                            driver
                                        )
                                )
                                .join("")}
                        `
                        : `
                            <div class="rca-subtitle">
                                Primary Drivers
                            </div>

                            <div
                                style="
                                    font-size: 10px;
                                    color: #64748b;
                                "
                            >
                                No directly supported primary driver was identified.
                            </div>
                        `
                }

                ${
                    secondaryDrivers.length > 0
                        ? `
                            <div class="rca-subtitle">
                                Secondary Drivers
                            </div>

                            ${secondaryDrivers
                                .map(
                                    (driver: any) =>
                                        this.renderRcaDriver(
                                            driver
                                        )
                                )
                                .join("")}
                        `
                        : ""
                }

                ${
                    recommendations.length > 0
                        ? `
                            <div class="rca-subtitle">
                                Recommendations
                            </div>

                            <ul class="rca-list">

                                ${recommendations
                                    .map(
                                        (item: any) =>
                                            `
                                                <li>
                                                    ${this.escapeHtml(
                                                        String(item)
                                                    )}
                                                </li>
                                            `
                                    )
                                    .join("")}

                            </ul>
                        `
                        : ""
                }

                ${
                    confidenceCaveats.length > 0
                        ? `
                            <div class="rca-subtitle">
                                Confidence & Caveats
                            </div>

                            ${confidenceCaveats
                                .map(
                                    (item: any) =>
                                        `
                                            <div class="rca-caveat">
                                                ${this.escapeHtml(
                                                    String(item)
                                                )}
                                            </div>
                                        `
                                )
                                .join("")}
                        `
                        : ""
                }

            </div>

        `;

    }

    private renderRcaDriver(
        driver: any
    ): string {

        const dimension =
            driver?.dimension
                ? String(driver.dimension)
                : "Dimension";

        const driverName =
            driver?.driver
                ? String(driver.driver)
                : "Driver";

        const evidence =
            driver?.evidence
                ? String(driver.evidence)
                : "";

        const impact =
            driver?.impact
                ? String(driver.impact)
                : "";

        const confidence =
            driver?.confidence
                ? String(driver.confidence)
                : "Low";

        const confidenceLower =
            confidence.toLowerCase();

        let confidenceClass =
            "rca-confidence-low";

        if (
            confidenceLower === "high"
        ) {

            confidenceClass =
                "rca-confidence-high";

        } else if (
            confidenceLower === "medium"
        ) {

            confidenceClass =
                "rca-confidence-medium";

        }

        return `

            <div class="rca-driver">

                <div class="rca-driver-header">

                    <div>

                        <div
                            class="rca-driver-name"
                        >
                            ${this.escapeHtml(
                                driverName
                            )}
                        </div>

                        <div
                            style="
                                font-size: 9px;
                                color: #64748b;
                                margin-top: 2px;
                            "
                        >
                            ${this.escapeHtml(
                                dimension
                            )}
                        </div>

                    </div>

                    <span
                        class="
                            rca-confidence
                            ${confidenceClass}
                        "
                    >
                        ${this.escapeHtml(
                            confidence
                        )}
                    </span>

                </div>

                ${
                    evidence
                        ? `
                            <div
                                class="rca-driver-row"
                            >
                                <span
                                    class="rca-driver-label"
                                >
                                    Evidence:
                                </span>

                                ${this.escapeHtml(
                                    evidence
                                )}
                            </div>
                        `
                        : ""
                }

                ${
                    impact
                        ? `
                            <div
                                class="rca-driver-row"
                            >
                                <span
                                    class="rca-driver-label"
                                >
                                    Impact:
                                </span>

                                ${this.escapeHtml(
                                    impact
                                )}
                            </div>
                        `
                        : ""
                }

            </div>

        `;

    }

    private buildRcaInsufficientHtml(
        evidence: any
    ): string {

        const reason =
            evidence && evidence.reason
                ? String(evidence.reason)
                : "Not enough data to run a root cause analysis.";

        return `

            <div class="rca-section">

                <div class="rca-title">
                    ✦ Root Cause Analysis
                </div>

                <div class="rca-caveat">
                    ${this.escapeHtml(reason)}
                </div>

            </div>

        `;

    }

    private buildRcaFailedHtml(): string {

        return `

            <div class="rca-section">

                <div class="rca-title">
                    ✦ Root Cause Analysis
                </div>

                <div class="rca-caveat">
                    Root cause analysis couldn't be generated this time. Try asking again.
                </div>

            </div>

        `;

    }

    // ============================================================
    // TOAST
    // ============================================================

    private showToast(
        message: string,
        type: "success" | "error" | "info" = "success"
    ) {

        const toastHost =
            this.container.querySelector(
                "#cortexToast"
            ) as HTMLElement | null;

        if (!toastHost) {
            return;
        }

        const toast =
            document.createElement(
                "div"
            );

        toast.className =
            `toast toast-${type} toast-notification toast-notification-${type}`;

        toast.textContent =
            message;

        toastHost.appendChild(
            toast
        );

        setTimeout(
            () => {

                toast.classList.add(
                    "toast-notification-fade-out"
                );

                setTimeout(
                    () => toast.remove(),
                    200
                );

            },
            2200
        );

    }

    // ============================================================
    // CSV
    // ============================================================

    private buildCsvContent(
        columns: string[],
        rows: any[]
    ): string {

        const csvRows: string[] = [];

        csvRows.push(
            columns
                .map(
                    column =>
                        this.escapeCsvValue(
                            String(column)
                        )
                )
                .join(",")
        );

        rows.forEach(
            (row: any) => {

                const values =
                    columns.map(
                        (column: string) => {

                            const value =
                                row[column] !== undefined &&
                                row[column] !== null
                                    ? row[column]
                                    : "";

                            return this.escapeCsvValue(
                                String(value)
                            );

                        }
                    );

                csvRows.push(
                    values.join(",")
                );

            }
        );

        return "\uFEFF" + csvRows.join("\r\n");

    }

    private async copyTextToClipboard(
        text: string
    ): Promise<boolean> {

        try {

            if (
                navigator.clipboard &&
                typeof navigator.clipboard.writeText === "function"
            ) {

                try {

                    await navigator.clipboard.writeText(
                        text
                    );

                    return true;

                } catch (clipboardError) {

                    console.warn(
                        "Clipboard API failed, using fallback:",
                        clipboardError
                    );

                }

            }

            const textArea =
                document.createElement(
                    "textarea"
                );

            textArea.value =
                text;

            textArea.setAttribute(
                "readonly",
                ""
            );

            textArea.style.position =
                "fixed";

            textArea.style.left =
                "-9999px";

            textArea.style.top =
                "-9999px";

            textArea.style.opacity =
                "0";

            document.body.appendChild(
                textArea
            );

            textArea.focus();

            textArea.select();

            textArea.setSelectionRange(
                0,
                textArea.value.length
            );

            let copied = false;

            try {

                copied =
                    document.execCommand(
                        "copy"
                    );

            } catch (execError) {

                console.warn(
                    "execCommand copy failed:",
                    execError
                );

            }

            document.body.removeChild(
                textArea
            );

            return copied;

        } catch (error) {

            console.error(
                "Clipboard copy failed:",
                error
            );

            return false;

        }

    }

    private async downloadCsv(
        columns: string[],
        rows: any[]
    ): Promise<boolean> {

        try {

            console.log(
                "Starting Power BI CSV download..."
            );

            const csvContent =
                this.buildCsvContent(
                    columns,
                    rows
                );

            if (!csvContent) {

                console.error(
                    "CSV content is empty"
                );

                return false;

            }

            if (!this.host.downloadService) {

                console.error(
                    "Power BI download service is unavailable."
                );

                this.showToast(
                    "Power BI download service is unavailable",
                    "error"
                );

                return false;

            }

            try {

                const status =
                    await this.host.downloadService.exportStatus();

                console.log(
                    "Power BI download status:",
                    status
                );

                if (
                    status !==
                    powerbi.PrivilegeStatus.Allowed
                ) {

                    console.error(
                        "Power BI download API is not allowed. Status:",
                        status
                    );

                    this.showToast(
                        "Downloads are not enabled for this custom visual",
                        "error"
                    );

                    return false;

                }

            } catch (statusError) {

                console.warn(
                    "Could not determine download API status:",
                    statusError
                );

            }

            const fileName =
                `cortex_analyst_result_${this.getTimestamp()}.csv`;

            const result =
                await this.host.downloadService.exportVisualsContent(
                    csvContent,
                    fileName,
                    "csv",
                    "Cortex Analyst query result"
                );

            console.log(
                "Power BI download result:",
                result
            );

            if (result) {

                this.showToast(
                    "CSV download started",
                    "success"
                );

                return true;

            }

            this.showToast(
                "Power BI could not download the CSV",
                "error"
            );

            return false;

        } catch (error: any) {

            console.error(
                "Power BI CSV download failed:",
                error
            );

            this.showToast(
                error?.message ||
                    "CSV download failed",
                "error"
            );

            return false;

        }

    }

    // ============================================================
    // UTILITIES
    // ============================================================

    private escapeCsvValue(
        value: string
    ): string {

        if (
            value.includes('"') ||
            value.includes(",") ||
            value.includes("\n") ||
            value.includes("\r")
        ) {

            return `"${value.replace(
                /"/g,
                '""'
            )}"`;

        }

        return value;

    }

    private escapeHtml(
        value: string
    ): string {

        return String(value)
            .replace(
                /&/g,
                "&amp;"
            )
            .replace(
                /</g,
                "&lt;"
            )
            .replace(
                />/g,
                "&gt;"
            )
            .replace(
                /"/g,
                "&quot;"
            )
            .replace(
                /'/g,
                "&#039;"
            );

    }

    private getTimestamp(): string {

        const now =
            new Date();

        return now
            .toISOString()
            .replace(
                /[:.]/g,
                "-"
            );

    }

}