import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans_Arabic } from "next/font/google";

import "./globals.css";
import { Providers } from "./providers";

/**
 * Fonts are self-hosted by `next/font` rather than pulled from a Google
 * stylesheet: the app must render correctly on a print-shop machine with no
 * outbound internet, and a blocking external stylesheet would leave Arabic
 * falling back to a system face.
 */
const sans = IBM_Plex_Sans_Arabic({
  subsets: ["arabic", "latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-sans",
  display: "swap",
});

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "مطبعة — أتمتة المطبوعات",
  description:
    "ارفع ملف Excel واحصل على ملف PDF جاهز للطبع، دون فتح أي برنامج تصميم.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ar" dir="rtl" className={`${sans.variable} ${mono.variable}`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
