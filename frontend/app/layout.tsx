import type { Metadata } from "next";
import "../styles/tokens.css";
import "./globals.css";
import TopNav from "@/components/TopNav";
import ChatDock from "@/components/chat/ChatDock";

export const metadata: Metadata = {
  title: "Practice Management",
  description: "Practice Management Dashboard",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <TopNav />
        <div className="wrap">{children}</div>
        <ChatDock />{/* Round E — chat on every page, gated by global.chat */}
      </body>
    </html>
  );
}
