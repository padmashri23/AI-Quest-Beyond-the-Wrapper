import { describe, expect, it } from "vitest";
import { number, request, send, session } from "../workspace";
import { failure, json, mockFetch, user } from "./fixtures";

const fixed = (value: number, digits: number) =>
  value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });

describe("number", () => {
  it("renders a dash for missing values", () => {
    expect(number(null)).toBe("—");
    expect(number(undefined)).toBe("—");
  });

  it("fixes the number of decimals", () => {
    expect(number("1234.5")).toBe(fixed(1234.5, 2));
    expect(number(2, 0)).toBe(fixed(2, 0));
    expect(number("0.123456", 4)).toBe(fixed(0.123456, 4));
  });
});

describe("request", () => {
  it("prefixes /api, sends the CSRF token and JSON headers", async () => {
    const fetchMock = mockFetch({ "POST /runs/1/approve": { ok: true } });
    session(user);
    await expect(send("/runs/1/approve", { statement: "x" })).resolves.toEqual({
      ok: true,
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/runs/1/approve");
    expect(init?.credentials).toBe("same-origin");
    expect(init?.headers).toMatchObject({
      "X-CSRF-Token": "csrf-token",
      "Content-Type": "application/json",
    });
    expect(init?.body).toBe(JSON.stringify({ statement: "x" }));
  });

  it("does not force a JSON content type for multipart bodies", async () => {
    const fetchMock = mockFetch({ "POST /runs": {} });
    await request("/runs", { method: "POST", body: new FormData() });
    const headers = fetchMock.mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
    expect(headers["X-CSRF-Token"]).toBe("");
  });

  it("throws the server's detail string", async () => {
    mockFetch({ "GET /runs/x": failure("Inventory not found", 404) });
    await expect(request("/runs/x")).rejects.toThrow("Inventory not found");
  });

  it("serialises structured validation errors", async () => {
    mockFetch({
      "GET /runs/x": json({ detail: [{ loc: ["body", "quantity"], msg: "invalid" }] }, 422),
    });
    await expect(request("/runs/x")).rejects.toThrow('"msg":"invalid"');
  });

  it("falls back to the status text when the body is not JSON", async () => {
    mockFetch({
      "GET /runs/x": new Response("<html>", { status: 502, statusText: "Bad Gateway" }),
    });
    await expect(request("/runs/x")).rejects.toThrow("Bad Gateway");
  });
});
