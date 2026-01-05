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

    const normalized = normalizeContent(text);
    
    // First, handle numbered lists specially - they may span multiple "blocks"
    // Process the entire text line by line to properly group list items
    const lines = normalized.split('\n');
    let i = 0;
    
    while (i < lines.length) {
      const line = lines[i];
      
      // Skip empty lines at the start
      if (!line.trim()) {
        i++;
        continue;
      }
      
      // Check for code blocks
      if (line.trim().startsWith('```')) {
        const language = line.trim().slice(3) || 'plaintext';
        const codeLines: string[] = [];
        i++;
        while (i < lines.length && !lines[i].trim().startsWith('```')) {
          codeLines.push(lines[i]);
          i++;
        }
        i++; // skip closing ```
        elements.push(
          <pre key={`code-${key++}`} className="bg-gray-900 border border-gray-700 rounded p-3 overflow-x-auto my-2">
            <code className={`language-${language} text-sm text-gray-300`}>
              {codeLines.join('\n')}
            </code>
          </pre>
        );
        continue;
      }
      
      // Check for headings
      const headingMatch = line.match(/^(#{1,6})\s+(.*?)$/);
      if (headingMatch) {
        const level = headingMatch[1].length;
        const headingText = headingMatch[2];
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
            children: parseInlineMarkdown(headingText),
          })
        );
        i++;
        continue;
      }
      
      // Check for numbered list (collect all items including sub-items)
      if (line.trim().match(/^\d+\.\s/)) {
        const listItems: { main: string; subItems: string[] }[] = [];
        
        while (i < lines.length) {
          const currentLine = lines[i];
          
          // New numbered item
          const numberedMatch = currentLine.match(/^\d+\.\s+(.*)/);
          if (numberedMatch) {
            listItems.push({ main: numberedMatch[1], subItems: [] });
            i++;
            continue;
          }
          
          // Sub-item (indented with - or *)
          const subItemMatch = currentLine.match(/^\s+[-*]\s+(.*)/);
          if (subItemMatch && listItems.length > 0) {
            listItems[listItems.length - 1].subItems.push(subItemMatch[1]);
            i++;
            continue;
          }
          
          // Empty line - might be between list items, peek ahead
          if (!currentLine.trim()) {
            // Check if next non-empty line is a numbered item
            let nextNonEmpty = i + 1;
            while (nextNonEmpty < lines.length && !lines[nextNonEmpty].trim()) {
              nextNonEmpty++;
            }
            if (nextNonEmpty < lines.length && lines[nextNonEmpty].match(/^\d+\.\s/)) {
              i++;
              continue;
            }
            // Not part of the list anymore
            break;
          }
          
          // Not a list item, stop processing list
          break;
        }
        
        // Render the numbered list
        elements.push(
          <ol key={`ol-${key++}`} className="list-decimal space-y-2 my-2 ml-4">
            {listItems.map((item, idx) => (
              <li key={`li-${key++}-${idx}`}>
                {parseInlineMarkdown(item.main)}
                {item.subItems.length > 0 && (
                  <ul className="list-disc ml-4 mt-1 space-y-1">
                    {item.subItems.map((sub, subIdx) => (
                      <li key={`sub-${key++}-${subIdx}`}>{parseInlineMarkdown(sub)}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ol>
        );
        continue;
      }
      
      // Check for bullet list
      if (line.trim().match(/^[-*+]\s/)) {
        const items: string[] = [];
        while (i < lines.length && lines[i].trim().match(/^[-*+]\s/)) {
          items.push(lines[i].replace(/^[-*+]\s/, ''));
          i++;
        }
        elements.push(
          <ul key={`ul-${key++}`} className="list-disc space-y-1 my-2 ml-4">
            {items.map((item, idx) => (
              <li key={`bullet-${key++}-${idx}`}>{parseInlineMarkdown(item)}</li>
            ))}
          </ul>
        );
        continue;
      }
      
      // Regular paragraph - collect consecutive non-empty lines
      const paragraphLines: string[] = [];
      while (i < lines.length && lines[i].trim() && 
             !lines[i].match(/^#{1,6}\s/) && 
             !lines[i].match(/^\d+\.\s/) &&
             !lines[i].match(/^[-*+]\s/) &&
             !lines[i].startsWith('```')) {
        paragraphLines.push(lines[i]);
        i++;
      }
      
      if (paragraphLines.length > 0) {
        elements.push(
          <p key={`paragraph-${key++}`} className="my-2 whitespace-pre-line">
            {parseInlineMarkdown(paragraphLines.join('\n'))}
          </p>
        );
      }
    }

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
