// マークダウン表示用のごく軽量なレンダラ。依存を増やさずに見出し・段落・
// 箇条書き・引用・強調だけサポートする。

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function inline(s: string): string {
  // **bold**
  let out = escapeHtml(s).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  // *italic* (loose)
  out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  // `code`
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  return out;
}

export function renderMarkdown(md: string): string {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const html: string[] = [];
  let inList = false;
  let inQuote = false;
  let para: string[] = [];

  const flushPara = () => {
    if (para.length === 0) return;
    html.push(`<p>${inline(para.join(" "))}</p>`);
    para = [];
  };
  const closeList = () => {
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
  };
  const closeQuote = () => {
    if (inQuote) {
      html.push("</blockquote>");
      inQuote = false;
    }
  };

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");

    if (line === "") {
      flushPara();
      closeList();
      closeQuote();
      continue;
    }

    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      flushPara();
      closeList();
      closeQuote();
      const level = h[1].length;
      html.push(`<h${level}>${inline(h[2])}</h${level}>`);
      continue;
    }

    const li = /^[-*]\s+(.*)$/.exec(line);
    if (li) {
      flushPara();
      closeQuote();
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${inline(li[1])}</li>`);
      continue;
    }

    const bq = /^>\s?(.*)$/.exec(line);
    if (bq) {
      flushPara();
      closeList();
      if (!inQuote) {
        html.push("<blockquote>");
        inQuote = true;
      }
      html.push(`<p>${inline(bq[1])}</p>`);
      continue;
    }

    if (line === "---") {
      flushPara();
      closeList();
      closeQuote();
      html.push("<hr />");
      continue;
    }

    para.push(line);
  }

  flushPara();
  closeList();
  closeQuote();

  return html.join("\n");
}
