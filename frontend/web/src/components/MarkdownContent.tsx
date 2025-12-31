import React from 'react';

interface MarkdownContentProps {
  content: string;
  className?: string;
}

/**
 * Simple Markdown renderer that converts basic Markdown to HTML
 * Supports: headings, bold, italic, code blocks, links, lists
 */
export function MarkdownContent({ content, className = '' }: MarkdownContentProps) {
  const normalizeContent = (text: string): string => {
    let normalized = text.replace(/\r\n/g, '\n');
    // Ensure numbered/bullet lists split onto new lines when inlined.
    normalized = normalized.replace(/([^\n])\s+(\d+\.\s)/g, '$1\n$2');
    normalized = normalized.replace(/([^\n])\s+([-*+]\s)/g, '$1\n$2');
    return normalized;
  };

  // Parse markdown and convert to React elements
  const parseMarkdown = (text: string): React.ReactNode[] => {
    const elements: React.ReactNode[] = [];
    let key = 0;

    // Split by double newlines to find paragraphs/blocks
    const blocks = normalizeContent(text).split(/\n\n+/);

    blocks.forEach((block) => {
      // Code blocks with ```
      const codeBlockMatch = block.match(/```(.+?)\n([\s\S]*?)```/);
      if (codeBlockMatch) {
        const language = codeBlockMatch[1] || 'plaintext';
        const code = codeBlockMatch[2].trim();
        elements.push(
          <pre key={`code-${key++}`} className="bg-gray-900 border border-gray-700 rounded p-3 overflow-x-auto my-2">
            <code className={`language-${language} text-sm text-gray-300`}>
              {code}
            </code>
          </pre>
        );
        return;
      }

      // Headings (# ## ###)
      const headingMatch = block.match(/^(#{1,6})\s+(.*?)$/m);
      if (headingMatch) {
        const level = headingMatch[1].length;
        const text = headingMatch[2];
        const HeadingTag = `h${level}` as keyof JSX.IntrinsicElements;
        const headingClasses = {
          h1: 'text-2xl font-bold mt-4 mb-2',
          h2: 'text-xl font-bold mt-3 mb-2',
          h3: 'text-lg font-bold mt-2 mb-1',
          h4: 'text-base font-bold mt-2 mb-1',
          h5: 'font-bold mt-1 mb-1',
          h6: 'font-bold mt-1 mb-1',
        };
        elements.push(
          React.createElement(HeadingTag, {
            key: `heading-${key++}`,
            className: headingClasses[`h${level}` as keyof typeof headingClasses],
            children: parseInlineMarkdown(text),
          })
        );
        return;
      }

      // Lists (bullet or numbered)
      const lines = block.split('\n').filter(line => line.trim());
      const isBulletList = lines.some(line => line.trim().match(/^[-*+]\s/));
      const isNumberedList = lines.some(line => line.trim().match(/^\d+\.\s/));

      if (isBulletList) {
        const items = lines
          .filter(line => line.trim().match(/^[-*+]\s/))
          .map((line) => (
            <li key={`bullet-${key++}`} className="ml-4">
              {parseInlineMarkdown(line.replace(/^[-*+]\s/, ''))}
            </li>
          ));
        if (items.length > 0) {
          elements.push(
            <ul key={`ul-${key++}`} className="list-disc space-y-1 my-2">
              {items}
            </ul>
          );
          return;
        }
      }

      if (isNumberedList) {
        const items = lines
          .filter(line => line.trim().match(/^\d+\.\s/))
          .map((line) => (
            <li key={`numbered-${key++}`} className="ml-4">
              {parseInlineMarkdown(line.replace(/^\d+\.\s/, ''))}
            </li>
          ));
        if (items.length > 0) {
          elements.push(
            <ol key={`ol-${key++}`} className="list-decimal space-y-1 my-2">
              {items}
            </ol>
          );
          return;
        }
      }

      // Regular paragraph with inline formatting
      if (block.trim()) {
        elements.push(
          <p key={`paragraph-${key++}`} className="my-2 whitespace-pre-line">
            {parseInlineMarkdown(block)}
          </p>
        );
      }
    });

    return elements;
  };

  // Parse inline markdown (bold, italic, code, links)
  const parseInlineMarkdown = (text: string): React.ReactNode[] => {
    const elements: React.ReactNode[] = [];
    let lastIndex = 0;
    let key = 0;

    // Combined regex for bold, italic, code, and links
    const regex = /\*\*(.+?)\*\*|__(.+?)__|\*(.+?)\*|_(.+?)_|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)/g;

    let match;
    while ((match = regex.exec(text)) !== null) {
      // Add text before the match
      if (match.index > lastIndex) {
        elements.push(text.slice(lastIndex, match.index));
      }

      // Add the formatted element
      if (match[1] || match[2]) {
        // Bold **text** or __text__
        elements.push(
          <strong key={`bold-${key++}`} className="font-bold">
            {match[1] || match[2]}
          </strong>
        );
      } else if (match[3] || match[4]) {
        // Italic *text* or _text_
        elements.push(
          <em key={`italic-${key++}`} className="italic">
            {match[3] || match[4]}
          </em>
        );
      } else if (match[5]) {
        // Code `text`
        elements.push(
          <code
            key={`code-${key++}`}
            className="bg-gray-700 px-2 py-0.5 rounded text-sm font-mono"
          >
            {match[5]}
          </code>
        );
      } else if (match[6] && match[7]) {
        // Link [text](url)
        elements.push(
          <a
            key={`link-${key++}`}
            href={match[7]}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-400 hover:text-blue-300 underline"
          >
            {match[6]}
          </a>
        );
      }

      lastIndex = regex.lastIndex;
    }

    // Add remaining text
    if (lastIndex < text.length) {
      elements.push(text.slice(lastIndex));
    }

    return elements.length > 0 ? elements : [text];
  };

  return (
    <div className={`prose prose-invert max-w-none ${className}`}>
      {parseMarkdown(content)}
    </div>
  );
}
