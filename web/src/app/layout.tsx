import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "서울 예약 오픈 일정",
  description: "서울 식당의 다음 예약 오픈 시각을 시간순으로 — 오픈런 준비용 시간표",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className="h-full">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@300;400;500;600&display=swap" rel="stylesheet" />
      </head>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
