import { useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Download, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useInstallPrompt } from "@/hooks/useInstallPrompt";

/**
 * PWA install prompt banner.
 *
 * Renders at the top of the main content area when:
 * - The browser has fired `beforeinstallprompt` (a deferred prompt is available).
 * - The app is not already installed (not running in standalone mode).
 * - The user has not dismissed the banner within the last 7 days.
 */
export function InstallBanner() {
  const { t } = useTranslation("common");
  const { canInstall, promptInstall, dismiss } = useInstallPrompt();

  const handleInstall = useCallback(async () => {
    await promptInstall();
  }, [promptInstall]);

  return (
    <AnimatePresence>
      {canInstall && (
      <motion.div
        key="install-banner"
        initial={{ height: 0, opacity: 0 }}
        animate={{ height: "auto", opacity: 1 }}
        exit={{ height: 0, opacity: 0 }}
        transition={{ duration: 0.25, ease: "easeInOut" }}
        className="overflow-hidden"
      >
        <div className="flex items-center gap-3 bg-purple-50 px-4 py-2.5 text-sm text-purple-900 dark:bg-purple-900/20 dark:text-purple-200">
          {/* Left: icon + text */}
          <Download className="size-4 shrink-0" />
          <div className="flex-1 min-w-0">
            <span className="font-medium">
              {t("installBanner.title")}
            </span>
            <span className="ml-1.5 hidden sm:inline">
              {t("installBanner.description")}
            </span>
          </div>

          {/* Right: action buttons */}
          <div className="flex shrink-0 items-center gap-2">
            <button
              onClick={handleInstall}
              className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-3 py-1 text-xs font-medium text-white hover:bg-purple-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 focus-visible:ring-offset-2 dark:bg-purple-700 dark:hover:bg-purple-600"
            >
              <Download className="size-3.5" />
              {t("installBanner.install")}
            </button>
            <button
              onClick={dismiss}
              className="rounded-md p-1 text-purple-600/70 hover:text-purple-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 dark:text-purple-300/70 dark:hover:text-purple-200"
              aria-label={t("installBanner.dismiss")}
            >
              <X className="size-4" />
            </button>
          </div>
        </div>
      </motion.div>
      )}
    </AnimatePresence>
  );
}
