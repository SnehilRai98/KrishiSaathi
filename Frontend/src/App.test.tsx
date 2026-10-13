import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { mockFetch } from "./test/helpers";

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("renders the dashboard and navigates between the two modules", async () => {
    mockFetch([["/api/", () => []]]);
    render(<App />);
    expect(screen.getByRole("heading", { name: /smarter decisions on the farm/i })).toBeInTheDocument();
    const nav = within(screen.getByRole("navigation", { name: "Main" }));
    expect(nav.getAllByRole("link").map((link) => link.textContent)).toEqual(["KrishiSaathi", "Home", "Crop health", "Fertilizer planner"].slice(1));
    await userEvent.click(nav.getByRole("link", { name: /fertilizer planner/i }));
    expect(await screen.findByRole("heading", { name: "Fertilizer planner" })).toBeInTheDocument();
    await userEvent.click(nav.getByRole("link", { name: /crop health/i }));
    expect(await screen.findByRole("heading", { name: "Crop health" })).toBeInTheDocument();
  });

  it("no longer offers a government schemes page", async () => {
    mockFetch([["/api/", () => []]]);
    window.history.pushState({}, "", "/schemes");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /government schemes/i })).not.toBeInTheDocument();
    window.history.pushState({}, "", "/");
  });
});
