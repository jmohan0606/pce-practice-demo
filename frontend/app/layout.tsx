import type { Metadata } from "next";
import "../styles/tokens.css";
import "./globals.css";
import TopNav from "@/components/TopNav";

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
      </body>
    </html>
  );
}
