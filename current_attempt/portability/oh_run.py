#!/usr/bin/env python3
"""In-container OpenHands headless runner for the unified 3-agent harness. Runs the OpenHands
SDK agent with LocalWorkspace on <workdir>, driven by the SAME prompt opencode/kilo get (skill
via /skill mount + AGENTS.md), NO skill-loader, NO harness force-apply. Env: OC_BASE, OC_MODEL,
OC_KEY. Args: <workdir> <prompt>."""
import os, sys, traceback
workdir, prompt = sys.argv[1], sys.argv[2]
try:
    from openhands.sdk import LLM, Agent, Conversation, LocalWorkspace
    from openhands.tools.preset.default import get_default_tools
    from openhands.sdk.context.condenser import LLMSummarizingCondenser
    from pydantic import SecretStr
    base, model, key = os.environ["OC_BASE"], "openai/" + os.environ["OC_MODEL"], SecretStr(os.environ["OC_KEY"])
    llm = LLM(model=model, base_url=base, api_key=key, usage_id="ohrun",
              max_output_tokens=4096, temperature=0.0, native_tool_calling=True)
    cond = LLM(model=model, base_url=base, api_key=key, usage_id="ohcond",
               max_output_tokens=4096, temperature=0.0, native_tool_calling=False)
    agent = Agent(llm=llm, tools=get_default_tools(enable_browser=False),
                  condenser=LLMSummarizingCondenser(llm=cond, max_size=40, keep_first=2))
    conv = Conversation(agent=agent, workspace=LocalWorkspace(working_dir=workdir), max_iteration_per_run=80)
    conv.send_message(prompt)
    conv.run()
    print("OH_RUN_DONE")
except Exception as e:
    traceback.print_exc()
    print("OH_RUN_ERROR", e)
