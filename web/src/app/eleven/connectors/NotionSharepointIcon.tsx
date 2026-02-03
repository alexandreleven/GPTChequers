/**
 * Eleven Edition - Notion Sharepoint Icon Component
 *
 * Custom icon component that combines Notion and Sharepoint icons
 * with a cross symbol between them to represent the integrated connector.
 */

import Image from "next/image";
import sharepointIcon from "@public/Sharepoint.png";
import notionIcon from "@public/Notion.png";

interface IconProps {
  size?: number;
  className?: string;
}

export const NotionSharepointIcon = ({
  size = 16,
  className = "",
}: IconProps) => {
  const crossSize = Math.max(8, size * 0.5); // Cross size relative to icon size

  return (
    <div
      className={`flex items-center gap-0.5 ${className}`}
      style={{ height: size }}
    >
      {/* Notion icon first */}
      <Image
        src={notionIcon}
        alt="Notion"
        width={size}
        height={size}
        className="object-contain"
      />

      {/* Cross symbol */}
      <span
        className="text-gray-400 font-light mx-0.5"
        style={{ fontSize: crossSize, lineHeight: `${size}px` }}
      >
        ×
      </span>

      {/* Sharepoint icon second */}
      <Image
        src={sharepointIcon}
        alt="Sharepoint"
        width={size}
        height={size}
        className="object-contain"
      />
    </div>
  );
};
