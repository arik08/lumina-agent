import { LoaderCircle, PackageCheck, PackagePlus, Trash2 } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";


interface MarketplaceInstallButtonProps {
  name: string;
  installed: boolean;
  pending: boolean;
  disabled?: boolean;
  onClick: () => void;
}


export function MarketplaceInstallButton({
  name,
  installed,
  pending,
  disabled = false,
  onClick,
}: MarketplaceInstallButtonProps) {
  const previousInstalled = useRef(installed);
  const [holdInstalledConfirmation, setHoldInstalledConfirmation] = useState(false);
  const justInstalled = installed && !previousInstalled.current;
  const keepInstalledVisible = installed && (justInstalled || holdInstalledConfirmation);

  useLayoutEffect(() => {
    if (justInstalled) {
      setHoldInstalledConfirmation(true);
    } else if (!installed) {
      setHoldInstalledConfirmation(false);
    }
    previousInstalled.current = installed;
  }, [installed, justInstalled]);

  const action = installed ? "Delete" : "Install";
  const releaseInstalledConfirmation = () => setHoldInstalledConfirmation(false);
  return (
    <button
      className={`skill-install-toggle ${installed ? "is-installed" : ""} ${pending ? "is-pending" : ""} ${keepInstalledVisible ? "keep-installed-visible" : ""}`.trim()}
      type="button"
      aria-label={`${name} ${action}`}
      aria-pressed={installed}
      aria-busy={pending}
      disabled={disabled || pending}
      onMouseMove={releaseInstalledConfirmation}
      onMouseLeave={releaseInstalledConfirmation}
      onClick={onClick}
    >
      {pending ? (
        <span className="marketplace-install-state">
          <span className="marketplace-install-icon"><LoaderCircle className="is-running" size={13} /></span>
          <span>{action}</span>
        </span>
      ) : installed ? (
        <span className="marketplace-install-state-stack">
          <span className="marketplace-install-state install-toggle-rest">
            <span className="marketplace-install-icon"><PackageCheck size={13} /></span>
            <span>Installed</span>
          </span>
          <span className="marketplace-install-state install-toggle-hover" aria-hidden="true">
            <span className="marketplace-install-icon"><Trash2 size={13} /></span>
            <span>Delete</span>
          </span>
        </span>
      ) : (
        <span className="marketplace-install-state">
          <span className="marketplace-install-icon"><PackagePlus size={13} /></span>
          <span>Install</span>
        </span>
      )}
    </button>
  );
}
