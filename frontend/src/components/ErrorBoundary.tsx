import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import i18n from "@/i18n";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  private handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const t = (key: string) => i18n.t(key);

      return (
        <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 p-8">
          <AlertTriangle className="size-12 text-destructive" />
          <h2 className="text-xl font-semibold text-foreground">{t("auth:errorBoundary.title")}</h2>
          <p className="max-w-md text-center text-sm text-muted-foreground">
            {this.state.error?.message ?? t("auth:errorBoundary.title")}
          </p>
          <Button variant="outline" onClick={this.handleReload}>
            {t("auth:errorBoundary.reloadPage")}
          </Button>
        </div>
      );
    }

    return this.props.children;
  }
}
