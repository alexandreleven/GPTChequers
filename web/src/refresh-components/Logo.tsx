"use client";

import { useSettingsContext } from "@/components/settings/SettingsProvider";
import Image from "next/image";
import {
  LOGO_FOLDED_SIZE_PX,
  LOGOTYPE_UNFOLDED_WIDTH_PX,
  LOGO_ROW_GAP_PX,
  NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED,
} from "@/lib/constants";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import { useMemo } from "react";

export interface LogoProps {
  folded?: boolean;
  size?: number;
  logotypeWidth?: number;
  className?: string;
}

export default function Logo({
  folded,
  size,
  logotypeWidth,
  className,
}: LogoProps) {
  const foldedSize = size ?? LOGO_FOLDED_SIZE_PX;
  const unfoldedLogotypeWidth = logotypeWidth ?? LOGOTYPE_UNFOLDED_WIDTH_PX;
  const logoRowGapPx = LOGO_ROW_GAP_PX;
  const unfoldedLogotypeHeight = Math.max(
    16,
    Math.round(unfoldedLogotypeWidth / 3.6)
  );
  const settings = useSettingsContext();
  const logoDisplayStyle = settings.enterpriseSettings?.logo_display_style;
  const applicationName = settings.enterpriseSettings?.application_name;
  const useCustomLogo = settings.enterpriseSettings?.use_custom_logo;
  const logoSrc = useCustomLogo ? "/api/enterprise-settings/logo" : "/logo.png";

  const logo = useMemo(
    () => (
      <div
        className={cn(
          "aspect-square overflow-hidden relative flex-shrink-0",
          useCustomLogo && "rounded-full",
          className
        )}
        style={{ height: foldedSize, width: foldedSize }}
      >
        <Image
          alt="Logo"
          src={logoSrc}
          fill
          className={cn(
            "object-center",
            useCustomLogo ? "object-cover" : "object-contain"
          )}
          sizes={`${foldedSize}px`}
        />
      </div>
    ),
    [className, foldedSize, logoSrc, useCustomLogo]
  );

  const logotype = (
    <Image
      alt="Logotype"
      src="/logotype.png"
      width={unfoldedLogotypeWidth}
      height={unfoldedLogotypeHeight}
      className={cn("h-auto object-contain object-left", className)}
      sizes={`${unfoldedLogotypeWidth}px`}
    />
  );

  const renderNameAndPoweredBy = (opts: {
    includeLogo: boolean;
    includeName: boolean;
    includeLogotype: boolean;
  }) => {
    return (
      <div className="flex flex-col min-w-0">
        <div
          className="flex flex-row items-center min-w-0"
          style={{ columnGap: `${logoRowGapPx}px` }}
        >
          {opts.includeLogo && logo}
          {opts.includeLogotype && !folded && logotype}
          {opts.includeName && !folded && (
            <div className="flex-1 min-w-0">
              <Truncated headingH3>{applicationName}</Truncated>
            </div>
          )}
        </div>
        {!NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED && !folded && (
          <Text
            secondaryBody
            text03
            className={cn(
              "line-clamp-1 truncate",
              opts.includeLogo &&
                (opts.includeName || opts.includeLogotype) &&
                "ml-[33px]"
            )}
            nowrap
          ></Text>
        )}
      </div>
    );
  };

  // Handle "logo_only" display style
  if (logoDisplayStyle === "logo_only") {
    return renderNameAndPoweredBy({
      includeLogo: true,
      includeName: false,
      includeLogotype: false,
    });
  }

  // Handle "name_only" display style
  if (logoDisplayStyle === "name_only") {
    return renderNameAndPoweredBy({
      includeLogo: false,
      includeName: true,
      includeLogotype: false,
    });
  }

  // Default behavior in unfolded state: logo + logotype aligned to the left.
  if (folded) {
    return logo;
  }

  return renderNameAndPoweredBy({
    includeLogo: true,
    includeName: false,
    includeLogotype: true,
  });
}
