import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock @base-ui/react/button to avoid its internal complexity in jsdom
vi.mock("@base-ui/react/button", () => ({
  Button: ({
    children,
    className,
    onClick,
    disabled,
    ...rest
  }: React.PropsWithChildren<{
    className?: string;
    onClick?: () => void;
    disabled?: boolean;
  }>) => (
    <button
      className={className}
      onClick={onClick}
      disabled={disabled}
      data-testid="button"
      {...rest}
    >
      {children}
    </button>
  ),
}));

import { Button, buttonVariants } from "@/components/ui/button";

describe("Button", () => {
  it("renders with default variant and size", () => {
    render(<Button>Click me</Button>);
    const btn = screen.getByTestId("button");
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveTextContent("Click me");
  });

  it("applies variant classes correctly", () => {
    const { rerender } = render(<Button variant="default">Default</Button>);
    const btn = screen.getByTestId("button");
    expect(btn.className).toContain("bg-primary");

    rerender(<Button variant="outline">Outline</Button>);
    expect(btn.className).toContain("border-border");

    rerender(<Button variant="destructive">Destructive</Button>);
    expect(btn.className).toContain("text-destructive");

    rerender(<Button variant="ghost">Ghost</Button>);
    expect(btn.className).toContain("hover:bg-muted");

    rerender(<Button variant="secondary">Secondary</Button>);
    expect(btn.className).toContain("bg-secondary");

    rerender(<Button variant="link">Link</Button>);
    expect(btn.className).toContain("underline-offset-4");
  });

  it("applies size classes correctly", () => {
    const { rerender } = render(<Button size="default">Default</Button>);
    const btn = screen.getByTestId("button");
    expect(btn.className).toContain("h-8");

    rerender(<Button size="sm">Small</Button>);
    expect(btn.className).toContain("h-7");

    rerender(<Button size="lg">Large</Button>);
    expect(btn.className).toContain("h-9");

    rerender(<Button size="xs">Extra Small</Button>);
    expect(btn.className).toContain("h-6");

    rerender(<Button size="icon">Icon</Button>);
    expect(btn.className).toContain("size-8");
  });

  it("merges custom className", () => {
    render(<Button className="my-custom-class">Custom</Button>);
    const btn = screen.getByTestId("button");
    expect(btn.className).toContain("my-custom-class");
  });

  it("handles click events", async () => {
    const handleClick = vi.fn();
    const user = userEvent.setup();
    render(<Button onClick={handleClick}>Click</Button>);

    await user.click(screen.getByTestId("button"));
    expect(handleClick).toHaveBeenCalledOnce();
  });

  it("passes disabled prop", () => {
    render(<Button disabled>Disabled</Button>);
    const btn = screen.getByTestId("button");
    expect(btn).toBeDisabled();
  });

  it("renders data-slot attribute", () => {
    render(<Button>Test</Button>);
    const btn = screen.getByTestId("button");
    expect(btn).toHaveAttribute("data-slot", "button");
  });
});

describe("buttonVariants", () => {
  it("returns a string of class names", () => {
    const result = buttonVariants();
    expect(typeof result).toBe("string");
    expect(result.length).toBeGreaterThan(0);
  });

  it("returns different classes for different variants", () => {
    const defaultClasses = buttonVariants({ variant: "default" });
    const outlineClasses = buttonVariants({ variant: "outline" });
    expect(defaultClasses).not.toBe(outlineClasses);
  });

  it("returns different classes for different sizes", () => {
    const defaultSize = buttonVariants({ size: "default" });
    const smSize = buttonVariants({ size: "sm" });
    expect(defaultSize).not.toBe(smSize);
  });
});
