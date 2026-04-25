const manifest = {"name":"XG Mobile"};
const API_VERSION = 2;
const internalAPIConnection = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
if (!internalAPIConnection) {
    throw new Error('[@decky/api]: Failed to connect to the loader as as the loader API was not initialized. This is likely a bug in Decky Loader.');
}
let api;
try {
    api = internalAPIConnection.connect(API_VERSION, manifest.name);
}
catch {
    api = internalAPIConnection.connect(1, manifest.name);
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version 1. Some features may not work.`);
}
if (api._version != API_VERSION) {
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version ${api._version}. Some features may not work.`);
}
const callable = api.callable;
const toaster = api.toaster;

// ── Backend calls ──────────────────────────────────────
const getStatus = callable("get_status");
const installNvidia = callable("install_nvidia");
const getProgress = callable("get_progress");
const activate = callable("activate_egpu");
const deactivate = callable("deactivate_egpu");
const getLaunchOptions = callable("get_launch_options");
const uninstallNvidia = callable("uninstall_nvidia");
const setupSudo = callable("setup_sudo");
function transition(prev, event) {
    switch (event.type) {
        case "install_click":
            return { status: "installing", step: 0, total: 8, msg: "Starting..." };
        case "uninstall_click":
            return { status: "uninstalling" };
        case "progress":
            return prev.status === "installing"
                ? { status: "installing", step: event.step, total: event.total, msg: event.msg }
                : prev;
        case "install_error":
            return prev.status === "installing"
                ? { ...prev, error: event.error, failedStep: event.failedStep }
                : prev;
        case "done":
            return prev.status === "installing" || prev.status === "uninstalling"
                ? { status: "idle" }
                : prev;
        case "boot_recover":
            if (event.operation === "installing")
                return { status: "installing", step: event.step, total: event.total || 8, msg: event.msg };
            if (event.operation === "uninstalling")
                return { status: "uninstalling" };
            return { status: "idle" };
        default:
            return prev;
    }
}
// ── Design tokens ──────────────────────────────────────
const C = {
    green: "#76b900",
    greenDim: "rgba(118, 185, 0, 0.15)",
    greenGlow: "rgba(118, 185, 0, 0.3)",
    red: "#e74c3c",
    redDim: "rgba(231, 76, 60, 0.15)",
    amber: "#f39c12",
    surface: "rgba(255, 255, 255, 0.03)",
    border: "rgba(255, 255, 255, 0.06)",
    textPrimary: "#e8eaed",
    textSecondary: "rgba(255, 255, 255, 0.5)",
    textMono: "'Consolas', 'Monaco', monospace",
};
const INSTALL_STEPS = {
    1: "Unlocking filesystem",
    2: "Initializing keys",
    3: "Freeing space",
    4: "Build environment",
    5: "Downloading nvidia",
    6: "Compiling module",
    7: "Auto-detection",
    8: "Loading driver",
};
// ── Helpers ────────────────────────────────────────────
const xgToast = (body) => toaster.toast({ title: "⚡ XG Mobile", body });
/** Format MB string to human-readable: "16376" → "16 GB", "376" → "376 MB" */
const fmtMem = (mb) => {
    const n = parseInt(mb);
    if (isNaN(n))
        return mb;
    if (n >= 1024)
        return `${(n / 1024).toFixed(n % 1024 === 0 ? 0 : 1)} GB`;
    return `${n} MB`;
};
/** Clean GPU name: "NVIDIA GeForce RTX 4090 Laptop GPU" → "RTX 4090" */
const fmtGpu = (name) => name.replace(/NVIDIA\s*/i, "").replace(/GeForce\s*/i, "").replace(/\s*Laptop\s*/i, " ").replace(/\s*GPU\s*/i, "").trim();
const sectionHeaderStyle = {
    fontSize: "11px",
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "1px",
};
// ── Styled micro-components ────────────────────────────
const Dot = ({ color, pulse }) => SP_REACT.createElement("span", {
    style: {
        display: "inline-block",
        width: "8px",
        height: "8px",
        borderRadius: "50%",
        backgroundColor: color,
        boxShadow: pulse ? `0 0 8px ${color}` : "none",
        animation: pulse ? "xgm-pulse 2s ease-in-out infinite" : "none",
        marginRight: "8px",
        flexShrink: 0,
    },
});
const StatusRow = ({ label, value, dot, pulse, mono }) => SP_REACT.createElement("div", {
    style: {
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "8px 0",
        borderBottom: `1px solid ${C.border}`,
    },
}, SP_REACT.createElement("span", { style: { color: C.textSecondary, fontSize: "12px", letterSpacing: "0.5px" } }, label), SP_REACT.createElement("span", {
    style: {
        display: "flex",
        alignItems: "center",
        color: C.textPrimary,
        fontSize: "13px",
        fontFamily: mono ? C.textMono : "inherit",
        fontWeight: 500,
    },
}, dot ? SP_REACT.createElement(Dot, { color: dot, pulse }) : null, value));
const Card = ({ children, accent }) => SP_REACT.createElement("div", {
    style: {
        background: C.surface,
        border: `1px solid ${accent ? accent.replace(")", ", 0.2)").replace("rgb", "rgba") : C.border}`,
        borderRadius: "8px",
        padding: "12px 14px",
        marginBottom: "8px",
    },
}, children);
const StatTile = ({ value, label, color, span, }) => SP_REACT.createElement("div", {
    style: {
        background: "rgba(255,255,255,0.03)",
        borderRadius: "4px",
        padding: "6px 8px",
        textAlign: "center",
        ...(span ? { gridColumn: "span 2" } : {}),
    },
}, SP_REACT.createElement("div", {
    style: {
        fontSize: "16px",
        fontFamily: C.textMono,
        color: color || C.textPrimary,
        fontWeight: 700,
    },
}, value), SP_REACT.createElement("div", {
    style: {
        fontSize: "9px",
        color: C.textSecondary,
        textTransform: "uppercase",
        letterSpacing: "0.5px",
    },
}, label));
const StepList = ({ current, total, error, failedStep, }) => {
    const rows = Array.from({ length: total }, (_, i) => {
        const stepNum = i + 1;
        const isFailed = !!(error && failedStep === stepNum);
        const isComplete = stepNum < current && !isFailed;
        const isCurrent = stepNum === current && !error;
        const dotBg = isFailed ? C.red : isComplete ? C.green : isCurrent ? C.amber : "rgba(255,255,255,0.12)";
        const textColor = isFailed ? C.red : isCurrent ? C.textPrimary : isComplete ? C.textSecondary : "rgba(255,255,255,0.35)";
        return SP_REACT.createElement("div", {
            key: i,
            style: {
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "3px 0",
            },
        }, 
        // Dot — real div block, not a Unicode char
        SP_REACT.createElement("div", {
            style: {
                width: "6px",
                height: "6px",
                borderRadius: "50%",
                backgroundColor: dotBg,
                flexShrink: 0,
                boxShadow: isCurrent ? `0 0 6px ${C.amber}` : "none",
                animation: isCurrent ? "xgm-pulse 2s ease-in-out infinite" : "none",
            },
        }), SP_REACT.createElement("span", {
            style: {
                fontSize: "12px",
                color: textColor,
                fontWeight: isCurrent || isFailed ? 600 : 400,
                letterSpacing: "0.3px",
            },
        }, INSTALL_STEPS[stepNum] || `Step ${stepNum}`));
    });
    return SP_REACT.createElement("div", { style: { padding: "4px 0" } }, ...rows);
};
const ActionButton = ({ onClick, children, variant = "primary", disabled }) => {
    const colors = {
        primary: { bg: C.greenDim, border: C.green, text: C.green },
        danger: { bg: C.redDim, border: C.red, text: C.red },
        ghost: { bg: "transparent", border: C.border, text: C.textSecondary },
    };
    const c = colors[variant];
    return SP_REACT.createElement(DFL.DialogButton, {
        onClick: disabled ? undefined : onClick,
        disabled,
        style: {
            width: "100%",
            padding: "10px 16px",
            background: c.bg,
            border: `1px solid ${c.border}`,
            borderRadius: "6px",
            color: disabled ? C.textSecondary : c.text,
            fontSize: "13px",
            fontWeight: 600,
            letterSpacing: "0.5px",
            opacity: disabled ? 0.5 : 1,
            textTransform: "uppercase",
            textAlign: "center",
            minWidth: "auto",
        },
    }, children);
};
const MiniSpinner = ({ label }) => SP_REACT.createElement(Card, null, SP_REACT.createElement("div", {
    style: {
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "16px 0",
        gap: "10px",
    },
}, SP_REACT.createElement("div", {
    style: {
        width: "24px",
        height: "24px",
        border: `2px solid ${C.border}`,
        borderTopColor: C.green,
        borderRadius: "50%",
        animation: "xgm-spin 0.8s linear infinite",
    },
}), SP_REACT.createElement("div", {
    style: {
        fontSize: "11px",
        color: C.textSecondary,
        letterSpacing: "0.5px",
    },
}, label)));
// ── Inject keyframes ───────────────────────────────────
const StyleInjector = () => SP_REACT.createElement("style", null, `
    @keyframes xgm-pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.4; }
    }
    @keyframes xgm-fadein {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes xgm-spin {
      to { transform: rotate(360deg); }
    }
    /* Gamepad focus highlight — target Steam's .gpfocus on DialogButton inside our panel */
    .xgm-panel .DialogButton.gpfocus,
    .xgm-panel .DialogButton:focus-visible {
      outline: none !important;
      box-shadow: 0 0 0 2px ${C.green}, 0 0 12px ${C.greenGlow} !important;
      filter: brightness(1.3) !important;
    }
    /* Remove default ToggleField bottom divider inside our Card */
    .xgm-panel .quickaccesscontrols_PanelSectionRow_2VQ88 > div:last-child {
      border-bottom: none !important;
    }
    .xgm-panel [class*="ToggleField"] > [class*="Description"] + div,
    .xgm-panel [class*="gamepaddialog_Field"] {
      border-bottom: none !important;
      margin-bottom: 0 !important;
      padding-bottom: 0 !important;
    }
  `);
// ── Main Panel ─────────────────────────────────────────
const XGMobilePanel = () => {
    const [phase, setPhase] = SP_REACT.useState({ status: "loading" });
    const [status, setStatus] = SP_REACT.useState({
        connected: false,
        enabled: false,
        gpu_on_bus: false,
        gpu_name: "",
        gpu_temp: "",
        gpu_mem: "",
        gpu_mem_total: "",
        gpu_power: "",
        nvidia_installed: false,
        nvidia_working: false,
        error: undefined,
    });
    const [error, setError] = SP_REACT.useState(null);
    const [copied, setCopied] = SP_REACT.useState(false);
    // Guard: when true, polling won't reset phase (waiting for sudo modal)
    const pendingSudo = SP_REACT.useRef(false);
    const handleError = (e, context) => {
        const msg = `${context}: ${e.message || e}`;
        setError(msg);
        xgToast(msg);
    };
    const refresh = async () => {
        try {
            const s = await getStatus();
            setStatus(s);
            if (s.error)
                setError(s.error);
        }
        catch (e) {
            setError(`Status unavailable: ${e.message || e}`);
        }
    };
    // Boot: show "Detecting dock..." until first real status arrives
    SP_REACT.useEffect(() => {
        const boot = async () => {
            try {
                const p = await getProgress();
                if (p.operation) {
                    setPhase(prev => transition(prev, {
                        type: "boot_recover", operation: p.operation, step: p.step, total: p.total, msg: p.msg,
                    }));
                    refresh(); // background update for recovering state
                    return;
                }
            }
            catch { }
            // Wait for real status before showing UI — avoids "Not connected" flash
            await refresh();
            setPhase({ status: "idle" });
        };
        boot();
        const interval = setInterval(refresh, 5000);
        return () => clearInterval(interval);
    }, []);
    // Progress polling during installing phase
    const isInstalling = phase.status === "installing";
    SP_REACT.useEffect(() => {
        if (!isInstalling)
            return;
        const interval = setInterval(async () => {
            if (pendingSudo.current)
                return; // waiting for password modal
            try {
                const p = await getProgress();
                if (p.operation !== "installing") {
                    setPhase(prev => transition(prev, { type: "done" }));
                    refresh();
                    return;
                }
                setPhase(prev => transition(prev, {
                    type: "progress", step: p.step, total: p.total || 8, msg: p.msg,
                }));
            }
            catch { }
        }, 1500);
        return () => clearInterval(interval);
    }, [isInstalling]);
    // Progress polling during uninstalling phase
    const isUninstalling = phase.status === "uninstalling";
    SP_REACT.useEffect(() => {
        if (!isUninstalling)
            return;
        const interval = setInterval(async () => {
            if (pendingSudo.current)
                return; // waiting for password modal
            try {
                const p = await getProgress();
                if (p.operation !== "uninstalling") {
                    setPhase(prev => transition(prev, { type: "done" }));
                    refresh();
                    return;
                }
            }
            catch { }
        }, 1500);
        return () => clearInterval(interval);
    }, [isUninstalling]);
    // ── Password modal ───────────────────────────────────
    // Returns the password string, or "" if cancelled.
    // NO Decky callables inside — modal only collects input.
    const askPassword = (action) => {
        return new Promise((resolve) => {
            let pw = "";
            let resolved = false;
            const done = (val) => { if (!resolved) {
                resolved = true;
                resolve(val);
            } };
            const modal = DFL.showModal(SP_REACT.createElement(DFL.ModalRoot, {
                closeModal: () => { done(""); modal.Close(); },
                onCancel: () => { done(""); modal.Close(); },
            }, SP_REACT.createElement("div", { style: { padding: "16px" } }, SP_REACT.createElement("div", {
                style: { ...sectionHeaderStyle, color: C.amber, marginBottom: "12px", fontSize: "14px" },
            }, action === "install" ? "Password required to install" : "Password required to uninstall"), SP_REACT.createElement("div", {
                style: { fontSize: "13px", color: C.textSecondary, marginBottom: "12px", lineHeight: "1.4" },
            }, "Enter your deck user password:"), SP_REACT.createElement(DFL.TextField, {
                label: "Password",
                bIsPassword: true,
                onChange: (e) => {
                    pw = typeof e === "string" ? e : e?.target?.value ?? "";
                },
            }), SP_REACT.createElement("div", { style: { display: "flex", gap: "8px", marginTop: "14px" } }, SP_REACT.createElement("div", { style: { flex: 1 } }, SP_REACT.createElement(ActionButton, {
                onClick: () => { done(pw.trim()); modal.Close(); },
                variant: "primary",
            }, action === "install" ? "Install" : "Uninstall")), SP_REACT.createElement("div", { style: { flex: 1 } }, SP_REACT.createElement(ActionButton, {
                onClick: () => { done(""); modal.Close(); },
                variant: "ghost",
            }, "Cancel"))))));
        });
    };
    // ── Sudo setup (called from main component, not modal) ──
    const doSudoSetup = async (action) => {
        pendingSudo.current = true;
        try {
            const pw = await askPassword(action);
            if (!pw)
                return false;
            // All Decky callables run HERE, in the main component context
            const sudoResult = await setupSudo(pw);
            if (!sudoResult.success) {
                setError(sudoResult.error || "Wrong password");
                return false;
            }
            return true;
        }
        finally {
            pendingSudo.current = false;
        }
    };
    // ── Install logic ─────────────────────────────────────
    const executeInstall = async () => {
        setPhase(prev => transition(prev, { type: "install_click" }));
        try {
            const result = await installNvidia();
            if (result.error === "needs_password") {
                // Stay in installing phase — modal overlays it
                const ok = await doSudoSetup("install");
                if (!ok) {
                    setPhase(prev => transition(prev, { type: "done" }));
                    return;
                }
                // Already in installing phase, just retry
                const retry = await installNvidia();
                if (retry.error) {
                    setError(retry.error);
                    if (retry.failed_step) {
                        setPhase(prev => transition(prev, { type: "install_error", error: true, failedStep: retry.failed_step }));
                        await new Promise((r) => setTimeout(r, 5000));
                    }
                }
                else if (retry.needs_reboot) {
                    xgToast("Driver installed. Reboot required to activate.");
                }
                else if (retry.success) {
                    xgToast(`${retry.gpu} ready!`);
                }
                return;
            }
            if (result.error) {
                setError(result.error);
                if (result.failed_step) {
                    setPhase(prev => transition(prev, { type: "install_error", error: true, failedStep: result.failed_step }));
                    await new Promise((r) => setTimeout(r, 5000));
                }
            }
            else if (result.needs_reboot) {
                xgToast("Driver installed. Reboot required to activate.");
            }
            else if (result.success) {
                xgToast(`${result.gpu} ready!`);
            }
        }
        catch (e) {
            handleError(e, "Install failed");
        }
        finally {
            setPhase(prev => prev.status === "installing" ? transition(prev, { type: "done" }) : prev);
            await refresh();
        }
    };
    const handleInstall = async () => {
        setError(null);
        await executeInstall();
    };
    const handleToggle = async (enable) => {
        setPhase({ status: enable ? "activating" : "deactivating" });
        setError(null);
        try {
            if (enable) {
                let result = await activate();
                if (result.error === "needs_password") {
                    const ok = await doSudoSetup("install");
                    if (!ok)
                        return;
                    result = await activate();
                }
                if (result.error) {
                    setError(result.error);
                }
                else {
                    xgToast(`${result.gpu_name} activated`);
                }
            }
            else {
                let result = await deactivate();
                if (result.error === "needs_password") {
                    const ok = await doSudoSetup("uninstall");
                    if (!ok)
                        return;
                    result = await deactivate();
                }
                if (result.result === "partial") {
                    xgToast("eGPU deactivated. Reboot recommended.");
                }
                else if (result.error) {
                    setError(result.error);
                }
                else {
                    xgToast("eGPU disabled. Safe to unplug.");
                }
            }
            await refresh();
        }
        catch (e) {
            handleError(e, enable ? "Activation failed" : "Deactivation failed");
        }
        finally {
            setPhase({ status: "idle" });
        }
    };
    const executeUninstall = async () => {
        setPhase(prev => transition(prev, { type: "uninstall_click" }));
        try {
            const result = await uninstallNvidia();
            if (result.error === "needs_password") {
                // Stay in uninstalling phase — modal overlays it
                const ok = await doSudoSetup("uninstall");
                if (!ok) {
                    setPhase(prev => transition(prev, { type: "done" }));
                    return;
                }
                // Already in uninstalling phase, just retry
                const retry = await uninstallNvidia();
                if (retry.error) {
                    setError(retry.error);
                }
                else {
                    xgToast("Driver removed.");
                }
                await refresh();
                return;
            }
            if (result.error) {
                setError(result.error);
            }
            else {
                xgToast("Driver removed.");
            }
            await refresh();
        }
        catch (e) {
            handleError(e, "Uninstall failed");
        }
        finally {
            setPhase(prev => prev.status === "uninstalling" ? transition(prev, { type: "done" }) : prev);
        }
    };
    const handleUninstall = async () => {
        setError(null);
        await executeUninstall();
    };
    const copyLaunchOptions = async () => {
        try {
            const opts = await getLaunchOptions();
            // Steam gamepad UI may not support navigator.clipboard — use fallback
            try {
                if (navigator.clipboard) {
                    await navigator.clipboard.writeText(opts);
                }
                else {
                    throw new Error("no clipboard API");
                }
            }
            catch {
                // Fallback: hidden textarea + execCommand
                const ta = document.createElement("textarea");
                ta.value = opts;
                ta.style.position = "fixed";
                ta.style.opacity = "0";
                document.body.appendChild(ta);
                ta.select();
                document.execCommand("copy");
                document.body.removeChild(ta);
            }
            setCopied(true);
            toaster.toast({ title: "Copied!", body: opts });
            setTimeout(() => setCopied(false), 3000);
        }
        catch (e) {
            handleError(e, "Copy failed");
        }
    };
    // ── Derived state ──────────────────────────────────
    const isIdle = phase.status === "idle";
    const isTransitioning = phase.status === "activating" || phase.status === "deactivating";
    const busy = !isIdle;
    const tempColor = parseInt(status.gpu_temp) > 80
        ? C.red
        : parseInt(status.gpu_temp) > 60
            ? C.amber
            : C.green;
    // ── Render ─────────────────────────────────────────
    return SP_REACT.createElement("div", { className: "xgm-panel", style: { animation: "xgm-fadein 0.3s ease" } }, SP_REACT.createElement(StyleInjector), 
    // Error banner (overlay - always visible)
    error &&
        SP_REACT.createElement(DFL.PanelSection, null, SP_REACT.createElement(DFL.PanelSectionRow, null, SP_REACT.createElement(Card, { accent: "rgb(231, 76, 60)" }, SP_REACT.createElement("div", {
            style: {
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
            },
        }, SP_REACT.createElement("div", { style: { flex: 1 } }, SP_REACT.createElement("div", { style: { ...sectionHeaderStyle, color: C.red, marginBottom: "4px" } }, "Error"), SP_REACT.createElement("div", {
            style: {
                fontSize: "12px",
                color: C.textSecondary,
                lineHeight: "1.4",
                wordBreak: "break-word",
            },
        }, error)), SP_REACT.createElement("button", {
            onClick: () => setError(null),
            style: {
                background: "none",
                border: "none",
                color: C.textSecondary,
                fontSize: "16px",
                cursor: "pointer",
                padding: "0 0 0 8px",
                lineHeight: 1,
            },
        }, "×"))))), 
    // Phase: loading
    phase.status === "loading" &&
        SP_REACT.createElement(DFL.PanelSection, null, SP_REACT.createElement(DFL.PanelSectionRow, null, SP_REACT.createElement(MiniSpinner, { label: "Detecting dock..." }))), 
    // Phase: installing
    phase.status === "installing" &&
        SP_REACT.createElement(DFL.PanelSection, null, SP_REACT.createElement(DFL.PanelSectionRow, null, SP_REACT.createElement(Card, { accent: "rgb(243, 156, 18)" }, SP_REACT.createElement("div", {
            style: {
                ...sectionHeaderStyle,
                color: C.amber,
                marginBottom: "12px",
                display: "flex",
                alignItems: "center",
                gap: "8px",
            },
        }, SP_REACT.createElement("div", {
            style: {
                width: "14px",
                height: "14px",
                border: `2px solid ${C.border}`,
                borderTopColor: C.amber,
                borderRadius: "50%",
                animation: "xgm-spin 0.8s linear infinite",
            },
        }), "Installing"), SP_REACT.createElement(StepList, {
            current: phase.step,
            total: phase.total || 8,
            error: phase.error,
            failedStep: phase.failedStep,
        })))), 
    // Phase: uninstalling
    phase.status === "uninstalling" &&
        SP_REACT.createElement(DFL.PanelSection, null, SP_REACT.createElement(DFL.PanelSectionRow, null, SP_REACT.createElement(MiniSpinner, { label: "Removing driver..." }))), 
    // Phases: idle / activating / deactivating - toggle first, then status
    (isIdle || isTransitioning) &&
        SP_REACT.createElement(DFL.PanelSection, null, 
        // Toggle — first element for gamepad focus & scroll
        status.connected &&
            SP_REACT.createElement(DFL.PanelSectionRow, null, SP_REACT.createElement(Card, { accent: status.enabled ? "rgb(118, 185, 0)" : undefined }, SP_REACT.createElement(DFL.ToggleField, {
                label: "eGPU Power",
                description: status.enabled
                    ? "Disable before unplugging"
                    : "Activate external GPU",
                checked: status.enabled,
                disabled: busy,
                onChange: handleToggle,
            }))), 
        // Status rows
        SP_REACT.createElement(DFL.PanelSectionRow, null, SP_REACT.createElement(Card, null, SP_REACT.createElement(StatusRow, {
            label: "Dock",
            value: status.connected ? "Connected" : "Not connected",
            dot: status.connected ? C.green : C.red,
            pulse: status.connected,
        }), status.connected &&
            SP_REACT.createElement(StatusRow, {
                label: "eGPU",
                value: isTransitioning
                    ? "Switching..."
                    : status.enabled
                        ? "Active"
                        : "Standby",
                dot: status.enabled ? C.green : C.amber,
                pulse: isTransitioning,
            }), status.nvidia_installed &&
            SP_REACT.createElement(StatusRow, {
                label: "Driver",
                value: status.nvidia_working
                    ? "Nvidia active"
                    : status.gpu_on_bus && !status.nvidia_working
                        ? "Nvidia not loaded"
                        : "Nvidia installed",
                dot: status.nvidia_working ? C.green
                    : status.gpu_on_bus ? C.amber
                        : C.textSecondary,
                pulse: status.gpu_on_bus && !status.nvidia_working,
            }))), 
        // Reboot needed banner — only when eGPU is on bus but driver isn't responding
        status.nvidia_installed &&
            status.gpu_on_bus &&
            !status.nvidia_working &&
            SP_REACT.createElement(DFL.PanelSectionRow, null, SP_REACT.createElement(Card, { accent: "rgb(243, 156, 18)" }, SP_REACT.createElement("div", {
                style: {
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    padding: "4px 0",
                },
            }, SP_REACT.createElement(Dot, { color: C.amber, pulse: true }), SP_REACT.createElement("div", {
                style: {
                    fontSize: "12px",
                    color: C.amber,
                    fontWeight: 500,
                    lineHeight: "1.4",
                },
            }, "Driver installed. Reboot required to activate."))))), 
    // GPU Stats (idle only)
    isIdle &&
        status.gpu_on_bus &&
        status.gpu_name &&
        SP_REACT.createElement(DFL.PanelSection, null, SP_REACT.createElement(DFL.PanelSectionRow, null, SP_REACT.createElement(Card, { accent: "rgb(118, 185, 0)" }, SP_REACT.createElement("div", {
            style: {
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "10px",
            },
        }, SP_REACT.createElement("span", { style: { ...sectionHeaderStyle, color: C.green } }, "GPU"), SP_REACT.createElement("span", {
            style: { fontSize: "13px", color: C.textPrimary, fontWeight: 600 },
        }, fmtGpu(status.gpu_name))), SP_REACT.createElement("div", {
            style: {
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "6px",
            },
        }, status.gpu_temp &&
            SP_REACT.createElement(StatTile, {
                value: `${status.gpu_temp}°`,
                label: "Temp",
                color: tempColor,
            }), status.gpu_power &&
            SP_REACT.createElement(StatTile, {
                value: `${Math.round(parseFloat(status.gpu_power))}W`,
                label: "TDP",
            })), status.gpu_mem &&
            SP_REACT.createElement("div", { style: { marginTop: "6px" } }, SP_REACT.createElement(StatTile, {
                value: status.gpu_mem_total
                    ? `${fmtMem(status.gpu_mem)} / ${fmtMem(status.gpu_mem_total)}`
                    : fmtMem(status.gpu_mem),
                label: "VRAM",
            }))))), 
    // Install section (idle, connected, no nvidia)
    isIdle &&
        status.connected &&
        !status.nvidia_installed &&
        SP_REACT.createElement(DFL.PanelSection, null, SP_REACT.createElement(DFL.PanelSectionRow, null, SP_REACT.createElement(Card, null, SP_REACT.createElement("div", {
            style: {
                fontSize: "12px",
                color: C.textSecondary,
                marginBottom: "10px",
                lineHeight: "1.4",
            },
        }, "Install nvidia driver + auto-detection service. Takes ~15 minutes."), SP_REACT.createElement(ActionButton, { onClick: handleInstall, variant: "primary" }, "⚡ Install nvidia driver")))), 
    // Games + Uninstall (idle, nvidia installed)
    isIdle &&
        status.nvidia_installed &&
        SP_REACT.createElement(DFL.PanelSection, null, SP_REACT.createElement(DFL.PanelSectionRow, null, SP_REACT.createElement(Card, null, SP_REACT.createElement("div", { style: { ...sectionHeaderStyle, color: C.textSecondary, marginBottom: "8px" } }, "Steam Launch Options"), SP_REACT.createElement("div", {
            style: {
                fontFamily: C.textMono,
                fontSize: "11px",
                color: C.green,
                background: "rgba(118, 185, 0, 0.08)",
                padding: "8px 10px",
                borderRadius: "4px",
                marginBottom: "10px",
                wordBreak: "break-all",
                lineHeight: "1.4",
            },
        }, 'DXVK_FILTER_DEVICE_NAME="RTX 4090" PROTON_ENABLE_NVAPI=1 DXVK_ENABLE_NVAPI=1 %command%'), SP_REACT.createElement(ActionButton, { onClick: copyLaunchOptions, variant: "ghost" }, copied ? "✓ Copied" : "Copy to clipboard"))), SP_REACT.createElement(DFL.PanelSectionRow, null, SP_REACT.createElement("div", { style: { marginTop: "8px" } }, SP_REACT.createElement(ActionButton, { onClick: handleUninstall, variant: "danger" }, "Uninstall driver")))));
};
// ── Plugin definition ──────────────────────────────────
var index = DFL.definePlugin(() => ({
    title: SP_REACT.createElement("div", { className: DFL.staticClasses.Title }, "XG Mobile"),
    content: SP_REACT.createElement(XGMobilePanel),
    icon: SP_REACT.createElement("span", { style: { fontSize: "18px" } }, "⚡"),
}));

export { index as default };
//# sourceMappingURL=index.js.map
