import readline from "node:readline";
import { ReplitConnectors } from "@replit/connectors-sdk";

const connectors = new ReplitConnectors();
const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });

for await (const line of input) {
  if (!line.trim()) continue;
  try {
    const request = JSON.parse(line);
    const response = await connectors.proxy(
      "telegram",
      `/${request.method}`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(request.body ?? {}),
      },
    );
    process.stdout.write(`${JSON.stringify(await response.json())}\n`);
  } catch (error) {
    process.stdout.write(`${JSON.stringify({
      ok: false,
      description: error instanceof Error ? error.message : String(error),
    })}\n`);
  }
}