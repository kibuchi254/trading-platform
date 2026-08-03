import { NextResponse } from "next/server";

export async function GET() {
  // Return downloadable DLL route response placeholder or precompiled DLL bytes
  return new NextResponse("ATLAS Bridge DLL download", {
    status: 200,
    headers: {
      "Content-Type": "application/octet-stream",
      "Content-Disposition": 'attachment; filename="atlas_bridge.dll"',
    },
  });
}
