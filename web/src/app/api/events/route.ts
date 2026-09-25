import type { NextRequest } from "next/server";
import { listEvents, type Range } from "@/lib/events";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const p = req.nextUrl.searchParams;
  const data = await listEvents({
    q: p.get("q") || undefined,
    range: (p.get("range") as Range) || undefined,
    region: p.get("region") || undefined,
    food: p.get("food") || undefined,
    cursor: p.get("cursor") || undefined,
  });
  return Response.json(data);
}
