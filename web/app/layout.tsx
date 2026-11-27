import type { Metadata } from "next";
import "@fontsource/barlow/400.css";
import "@fontsource/barlow/500.css";
import "@fontsource/barlow/600.css";
import "@fontsource/barlow-semi-condensed/500.css";
import "@fontsource/barlow-semi-condensed/600.css";
import "@fontsource-variable/martian-mono/wdth.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "EZRA UDP Debugger",
  description: "Send, watch and verify Deep Robotics inspection-protocol messages over UDP, DTLS, TCP and TLS.",
};

// Runs before paint so the theme never flashes.
const themeInit = `(function(){try{var t=localStorage.getItem('ezra.theme');if(t!=='light'&&t!=='dark'){t=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme='light'}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
