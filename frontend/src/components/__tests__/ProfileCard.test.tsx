import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("@/utils", () => ({
  getRatingColor: (elo: number) => {
    if (elo >= 2400) return "#FF0000";
    if (elo >= 2100) return "#FF8C00";
    return "#00FF00";
  },
  getDifficultyLabelKey: (elo: number) => `rating:${elo}`,
}));

vi.mock("html2canvas", () => ({
  default: vi.fn().mockResolvedValue({
    toDataURL: () => "data:image/png;base64,test",
  }),
}));

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import {
  ProfileCardExport,
  type ProfileCardProps,
} from "@/components/ProfileCard";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const defaultUser = {
  id: "user-1",
  username: "testuser",
  cf_handle: "testcf",
  elo: 1500,
  pp: 100,
  avatar_path: null,
};

const defaultOverallMedal = {
  type: "gold",
  level: "regional",
};

function makeProps(overrides: Partial<ProfileCardProps> = {}): ProfileCardProps {
  return {
    user: defaultUser,
    displayMode: "medal",
    overallMedal: defaultOverallMedal,
    totalMedals: 5,
    skillMedals: [],
    totalSolved: 42,
    streakDays: 7,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ProfileCardExport", () => {
  it("renders the export button", () => {
    render(<ProfileCardExport {...makeProps()} />);
    // t("exportCard") in the component returns "exportCard" from our mock
    expect(screen.getByText("exportCard")).toBeInTheDocument();
  });

  it("renders username in the card content", () => {
    render(<ProfileCardExport {...makeProps()} />);
    expect(screen.getByText("testuser")).toBeInTheDocument();
  });

  it("renders CF handle when present", () => {
    render(<ProfileCardExport {...makeProps()} />);
    expect(screen.getByText(/CF: testcf/)).toBeInTheDocument();
  });

  it("does not render CF handle when null", () => {
    render(
      <ProfileCardExport
        {...makeProps({ user: { ...defaultUser, cf_handle: null } })}
      />,
    );
    expect(screen.queryByText(/CF:/)).not.toBeInTheDocument();
  });

  it("renders Elo and PP values", () => {
    render(<ProfileCardExport {...makeProps()} />);
    expect(screen.getByText("1500")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
  });

  it("renders total medals", () => {
    render(<ProfileCardExport {...makeProps()} />);
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("renders total solved", () => {
    render(<ProfileCardExport {...makeProps()} />);
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("renders streak days", () => {
    render(<ProfileCardExport {...makeProps()} />);
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("renders PP rank when provided", () => {
    render(<ProfileCardExport {...makeProps({ ppRank: 42 })} />);
    expect(screen.getByText("#42")).toBeInTheDocument();
  });

  it("renders skill medals when provided", () => {
    render(
      <ProfileCardExport
        {...makeProps({
          skillMedals: [
            { tag: "dp", level: "regional", type: "gold" },
            { tag: "greedy", level: "provincial", type: "silver" },
          ],
        })}
      />,
    );
    expect(screen.getByText("dp")).toBeInTheDocument();
    expect(screen.getByText("greedy")).toBeInTheDocument();
  });

  it("renders skill medal without type as plain text", () => {
    render(
      <ProfileCardExport
        {...makeProps({
          skillMedals: [{ tag: "math", level: "unranked" }],
        })}
      />,
    );
    expect(screen.getByText("math")).toBeInTheDocument();
  });

  it("handles cf_tier display mode", () => {
    render(
      <ProfileCardExport {...makeProps({ displayMode: "cf_tier", overallMedal: null })} />,
    );
    // In cf_tier mode, should render rating label
    expect(screen.getByText("rating:1500")).toBeInTheDocument();
  });

  it("triggers export on click and returns to normal state", async () => {
    const user = userEvent.setup();
    render(<ProfileCardExport {...makeProps()} />);

    const button = screen.getByRole("button");
    await user.click(button);

    // After the export completes (html2canvas resolves immediately in mock),
    // the button text should return to "exportCard"
    await waitFor(() => {
      expect(screen.getByText("exportCard")).toBeInTheDocument();
    });
  });
});
