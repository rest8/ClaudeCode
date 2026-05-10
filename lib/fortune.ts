import Anthropic from "@anthropic-ai/sdk";
import { buildUserPrompt, FortuneRequest, SYSTEM_PROMPT } from "./prompt";
import { runRenreki, RenrekiResult } from "./renreki";

const DEFAULT_MODEL = "claude-sonnet-4-6";

export interface FortuneOutcome {
  profile: RenrekiResult;
  report: string;
}

export async function generateFortune(
  req: FortuneRequest,
  apiKey: string,
  model: string = process.env.ANTHROPIC_MODEL ?? DEFAULT_MODEL,
): Promise<FortuneOutcome> {
  const profile = runRenreki(req);
  const userPrompt = buildUserPrompt(req, profile);

  const client = new Anthropic({ apiKey });
  const message = await client.messages.create({
    model,
    max_tokens: 2400,
    system: SYSTEM_PROMPT,
    messages: [{ role: "user", content: userPrompt }],
  });

  const report = message.content
    .map((c) => (c.type === "text" ? c.text : ""))
    .join("\n")
    .trim();

  return { profile, report };
}
