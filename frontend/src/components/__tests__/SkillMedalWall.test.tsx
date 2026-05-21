import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("@/components/medal/MedalBadge", () => ({
  MedalBadge: ({ level, type }: { level: string; type?: string }) => (
    <span data-testid="medal-badge">
      {level}-{type ?? "none"}
    </span>
  ),
}));

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { SkillMedalWall } from "@/components/medal/SkillMedalWall";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SkillMedalWall", () => {
  it("shows no skills message when skills is empty", () => {
    render(<SkillMedalWall skills={[]} />);
    expect(screen.getByText("skills.noSkills")).toBeInTheDocument();
  });

  it("renders skill items with tags and badges", () => {
    const skills = [
      { tag: "dp", level: "regional", type: "gold" },
      { tag: "greedy", level: "provincial", type: "silver" },
    ];

    render(<SkillMedalWall skills={skills} />);
    expect(screen.getByText("dp")).toBeInTheDocument();
    expect(screen.getByText("greedy")).toBeInTheDocument();
    expect(screen.getAllByTestId("medal-badge").length).toBe(2);
  });

  it("renders skill items without type", () => {
    const skills = [
      { tag: "math", level: "unranked" },
    ];

    render(<SkillMedalWall skills={skills} />);
    expect(screen.getByText("math")).toBeInTheDocument();
    expect(screen.getByTestId("medal-badge")).toHaveTextContent("unranked-none");
  });

  it("applies custom className", () => {
    const { container } = render(
      <SkillMedalWall skills={[]} className="custom" />,
    );
    const root = container.firstElementChild as HTMLElement;
    expect(root.classList.contains("custom")).toBe(true);
  });
});
