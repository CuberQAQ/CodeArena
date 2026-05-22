import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PageHeader } from "@/components/PageHeader";

describe("PageHeader", () => {
  it("renders title", () => {
    render(<PageHeader title="Test Page" />);
    expect(screen.getByText("Test Page")).toBeInTheDocument();
  });

  it("renders description when provided", () => {
    render(<PageHeader title="Test" description="A test description" />);
    expect(screen.getByText("A test description")).toBeInTheDocument();
  });

  it("does not render description element when not provided", () => {
    const { container } = render(<PageHeader title="Test" />);
    // Only h1 should be present, no p element
    expect(container.querySelector("p")).toBeNull();
  });

  it("renders actions slot when provided", () => {
    render(<PageHeader title="Test" actions={<button>Action</button>} />);
    expect(screen.getByText("Action")).toBeInTheDocument();
  });

  it("does not render actions wrapper when not provided", () => {
    render(<PageHeader title="Test" />);
    // The actions div should not exist
    const h1 = screen.getByText("Test");
    const parent = h1.closest("div");
    // Parent should only contain the title div, not an actions div
    expect(parent?.children.length).toBe(1);
  });
});
