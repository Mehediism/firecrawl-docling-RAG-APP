import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
    title: "Firecrawl-Docling RAG",
    description: "RAG system powered by Firecrawl and Docling",
};

export default function RootLayout({
    children,
}: Readonly<{
    children: React.ReactNode;
}>) {
    return (
        <html lang="en">
            <body className="antialiased">
                {children}
            </body>
        </html>
    );
}
