import type { Metadata } from "next";
import SessionBootstrap from "@/components/SessionBootstrap";
import "./globals.css";

export const metadata: Metadata = {
  title: "Smart-CS Center",
  description: "Smart-CS Center · multi-product customer service console",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <SessionBootstrap />
        {children}
      </body>
    </html>
  );
}
