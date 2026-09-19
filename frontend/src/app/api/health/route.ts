import { NextResponse } from "next/server";

const BACKEND_INTERNAL_URL = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

export async function GET() {
  try {
    const response = await fetch(`${BACKEND_INTERNAL_URL}/health`, {
      cache: "no-store",
    });
    const body = await response.json();
    return NextResponse.json(body, { status: response.status });
  } catch {
    return NextResponse.json(
      { status: "error", postgres: "unknown" },
      { status: 502 },
    );
  }
}
