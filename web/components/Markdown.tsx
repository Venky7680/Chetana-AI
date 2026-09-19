"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

/**
 * A deliberately small Markdown renderer for provider setup instructions.
 *
 * Keep writes per-provider "point your tool at this webhook" instructions as
 * Markdown, with the URL and key already substituted. They are genuinely useful
 * — numbered steps, the exact header to paste — so rendering them as a wall of
 * plain text would waste them.
 *
 * Two constraints shaped this. It pulls in no dependency, because one renderer
 * is not worth a supply chain. And it never touches dangerouslySetInnerHTML:
 * this text originates in a third-party provider definition, so it is treated
 * as content, not as markup. Anything it does not understand degrades to plain
 * text rather than disappearing.
 */

function Inline({ text }: { text: string }) {
  // `code`, **bold**, and bare URLs. Everything else stays literal.
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|https?:\/\/[^\s)<>"]+)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (!part) return null;
        if (part.startsWith("`") && part.endsWith("`") && part.length > 1) {
          return (
            <code
              key={i}
              className="rounded bg-surface-overlay px-1 py-0.5 font-mono text-[0.8em] text-slate-300"
            >
              {part.slice(1, -1)}
            </code>
          );
        }
        if (part.startsWith("**") && part.endsWith("**") && part.length > 3) {
          return (
            <strong key={i} className="font-medium text-slate-200">
              {part.slice(2, -2)}
            </strong>
          );
        }
        if (/^https?:\/\//.test(part)) {
          return (
            <a
              key={i}
              href={part}
              target="_blank"
              rel="noreferrer noopener"
              className="break-all text-accent hover:underline"
            >
              {part}
            </a>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard is blocked in some contexts; the text is selectable anyway.
    }
  }

  return (
    <div className="relative">
      <pre className="overflow-x-auto rounded-lg border border-surface-border bg-surface-base px-3 py-2.5 pr-10 font-mono text-xs leading-relaxed text-slate-300">
        {code}
      </pre>
      <button
        onClick={copy}
        aria-label="Copy"
        className="absolute right-2 top-2 rounded-md border border-surface-border bg-surface-raised p-1.5 text-slate-500 transition hover:text-slate-200"
      >
        {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
      </button>
    </div>
  );
}

export function Markdown({ text }: { text: string }) {
  const blocks: React.ReactNode[] = [];
  const lines = text.replace(/\r\n/g, "\n").split("\n");

  let i = 0;
  let key = 0;
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  function flushParagraph() {
    if (paragraph.length === 0) return;
    blocks.push(
      <p key={key++} className="text-sm leading-relaxed text-slate-400">
        <Inline text={paragraph.join(" ")} />
      </p>,
    );
    paragraph = [];
  }

  function flushList() {
    if (!list) return;
    const { ordered, items } = list;
    const className = "ml-4 space-y-1.5 text-sm leading-relaxed text-slate-400";
    blocks.push(
      ordered ? (
        <ol key={key++} className={`list-decimal ${className}`}>
          {items.map((item, n) => (
            <li key={n} className="pl-1">
              <Inline text={item} />
            </li>
          ))}
        </ol>
      ) : (
        <ul key={key++} className={`list-disc ${className}`}>
          {items.map((item, n) => (
            <li key={n} className="pl-1">
              <Inline text={item} />
            </li>
          ))}
        </ul>
      ),
    );
    list = null;
  }

  function flushAll() {
    flushParagraph();
    flushList();
  }

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code.
    if (/^\s*```/.test(line)) {
      flushAll();
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !/^\s*```/.test(lines[i])) {
        body.push(lines[i]);
        i += 1;
      }
      i += 1;
      blocks.push(<CodeBlock key={key++} code={body.join("\n")} />);
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flushAll();
      blocks.push(
        <h4 key={key++} className="text-sm font-semibold text-slate-200">
          <Inline text={heading[2]} />
        </h4>,
      );
      i += 1;
      continue;
    }

    const ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
    if (ordered || bullet) {
      flushParagraph();
      const isOrdered = Boolean(ordered);
      const item = (ordered ?? bullet)![1];
      if (!list || list.ordered !== isOrdered) {
        flushList();
        list = { ordered: isOrdered, items: [] };
      }
      list.items.push(item);
      i += 1;
      continue;
    }

    if (line.trim() === "") {
      flushAll();
      i += 1;
      continue;
    }

    flushList();
    paragraph.push(line.trim());
    i += 1;
  }
  flushAll();

  return <div className="space-y-3">{blocks}</div>;
}
