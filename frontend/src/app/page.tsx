"use client";

import { useState, useRef, useEffect } from "react";
import { sendChatMessage } from "@/services/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { logger } from "@/utils/logger";
import Link from "next/link";

interface Message {
    role: "user" | "bot";
    content: string;
    image?: string;
}

export default function Home() {
    const [messages, setMessages] = useState<Message[]>([
        { role: "bot", content: "Hello! I'm your RAG assistant powered by Firecrawl and Docling. Ask me anything about the indexed content." },
    ]);
    const [input, setInput] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [selectedImage, setSelectedImage] = useState<string | null>(null);
    const [threadId, setThreadId] = useState<string>("");
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        const newThreadId = crypto.randomUUID();
        setThreadId(newThreadId);
        console.log("New session started with Thread ID:", newThreadId);
    }, []);

    useEffect(() => {
        scrollToBottom();
    }, [messages, selectedImage]);

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) {
            if (!file.type.startsWith("image/")) {
                alert("Please select a valid image file.");
                if (fileInputRef.current) fileInputRef.current.value = "";
                return;
            }

            const MAX_SIZE_MB = 5;
            if (file.size > MAX_SIZE_MB * 1024 * 1024) {
                alert(`Image size exceeds the ${MAX_SIZE_MB}MB limit.`);
                if (fileInputRef.current) fileInputRef.current.value = "";
                return;
            }

            const reader = new FileReader();
            reader.onloadend = () => {
                setSelectedImage(reader.result as string);
            };
            reader.readAsDataURL(file);
        }
    };

    const handleRemoveImage = () => {
        setSelectedImage(null);
        if (fileInputRef.current) {
            fileInputRef.current.value = "";
        }
    };

    const sendMessage = async () => {
        if (!input.trim() && !selectedImage) return;

        const userMessage: Message = { role: "user", content: input, image: selectedImage || undefined };
        setMessages((prev) => [...prev, userMessage]);

        const currentInput = input;
        const currentImage = selectedImage;
        setInput("");
        setSelectedImage(null);
        if (fileInputRef.current) fileInputRef.current.value = "";

        setIsLoading(true);

        logger.userAction("Send Chat Message", { length: currentInput.length, hasImage: !!currentImage });

        try {
            const data = await sendChatMessage(currentInput, threadId, currentImage || undefined);
            const botMessage: Message = { role: "bot", content: data.response };
            setMessages((prev) => [...prev, botMessage]);
            logger.success("Chat response received", { length: data.response.length });
        } catch (error) {
            logger.error("Error sending chat message", error);
            setMessages((prev) => [
                ...prev,
                { role: "bot", content: "Sorry, something went wrong. Please check if the backend is running." },
            ]);
        } finally {
            setIsLoading(false);
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter") {
            sendMessage();
        }
    };

    return (
        <div className="flex flex-col h-screen bg-gray-50 text-gray-800 font-sans">
            {/* Header */}
            <header className="bg-white shadow-sm p-4 sticky top-0 z-10">
                <div className="max-w-4xl mx-auto flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 bg-gradient-to-r from-orange-500 to-red-500 rounded-full flex items-center justify-center text-white font-bold text-xl">
                            🔥
                        </div>
                        <h1 className="text-xl font-bold text-gray-900">Firecrawl-Docling RAG</h1>
                    </div>
                    <Link
                        href="/source"
                        className="px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-gray-700 transition-colors"
                    >
                        Manage Sources
                    </Link>
                </div>
            </header>

            {/* Chat Area */}
            <main className="flex-1 overflow-y-auto p-4">
                <div className="max-w-4xl mx-auto space-y-4">
                    {messages.map((msg, index) => (
                        <div
                            key={index}
                            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                        >
                            <div
                                className={`max-w-[80%] p-4 rounded-2xl shadow-sm ${msg.role === "user"
                                    ? "bg-gradient-to-r from-orange-500 to-red-500 text-white rounded-tr-none"
                                    : "bg-white border border-gray-100 text-gray-800 rounded-tl-none"
                                    }`}
                            >
                                {msg.role === "user" ? (
                                    <div className="whitespace-pre-wrap">
                                        {msg.image && (
                                            <img src={msg.image} alt="User upload" className="max-w-xs h-auto rounded-lg mb-2 border border-white/20" />
                                        )}
                                        {msg.content}
                                    </div>
                                ) : (
                                    <div className="prose prose-sm max-w-none">
                                        <ReactMarkdown
                                            remarkPlugins={[remarkGfm]}
                                            components={{
                                                h1: ({ node, ...props }) => <h1 className="text-xl font-bold mt-4 mb-2" {...props} />,
                                                h2: ({ node, ...props }) => <h2 className="text-lg font-bold mt-3 mb-2" {...props} />,
                                                h3: ({ node, ...props }) => <h3 className="text-base font-bold mt-2 mb-1" {...props} />,
                                                p: ({ node, ...props }) => <p className="mb-2 last:mb-0" {...props} />,
                                                ul: ({ node, ...props }) => <ul className="list-disc list-inside mb-2 space-y-1" {...props} />,
                                                ol: ({ node, ...props }) => <ol className="list-decimal list-inside mb-2 space-y-1" {...props} />,
                                                li: ({ node, ...props }) => <li className="ml-2" {...props} />,
                                                code: ({ node, inline, ...props }: any) =>
                                                    inline ? (
                                                        <code className="bg-gray-100 text-orange-700 px-1.5 py-0.5 rounded text-sm font-mono" {...props} />
                                                    ) : (
                                                        <code className="block bg-gray-100 text-gray-800 p-3 rounded-lg overflow-x-auto text-sm font-mono mb-2" {...props} />
                                                    ),
                                                pre: ({ node, ...props }) => <pre className="mb-2" {...props} />,
                                                a: ({ node, ...props }) => (
                                                    <a className="text-orange-600 hover:text-orange-800 underline" target="_blank" rel="noopener noreferrer" {...props} />
                                                ),
                                                strong: ({ node, ...props }) => <strong className="font-bold" {...props} />,
                                                em: ({ node, ...props }) => <em className="italic" {...props} />,
                                                blockquote: ({ node, ...props }) => (
                                                    <blockquote className="border-l-4 border-orange-300 pl-4 italic my-2" {...props} />
                                                ),
                                                table: ({ node, ...props }) => (
                                                    <div className="overflow-x-auto my-3 rounded-lg border border-gray-200">
                                                        <table className="border-collapse w-full text-sm" {...props} />
                                                    </div>
                                                ),
                                                thead: ({ node, ...props }) => <thead className="bg-gray-100" {...props} />,
                                                tbody: ({ node, ...props }) => <tbody className="divide-y divide-gray-200" {...props} />,
                                                tr: ({ node, ...props }) => <tr className="even:bg-gray-50" {...props} />,
                                                th: ({ node, ...props }) => (
                                                    <th className="px-3 py-2 text-left font-semibold border-b border-gray-300" {...props} />
                                                ),
                                                td: ({ node, ...props }) => <td className="px-3 py-2 align-top" {...props} />,
                                            }}
                                        >
                                            {msg.content}
                                        </ReactMarkdown>
                                    </div>
                                )}
                            </div>
                        </div>
                    ))}
                    {isLoading && (
                        <div className="flex justify-start">
                            <div className="bg-white border border-gray-100 p-4 rounded-2xl rounded-tl-none shadow-sm flex items-center gap-2">
                                <div className="w-2 h-2 bg-orange-400 rounded-full animate-bounce"></div>
                                <div className="w-2 h-2 bg-orange-400 rounded-full animate-bounce delay-75"></div>
                                <div className="w-2 h-2 bg-orange-400 rounded-full animate-bounce delay-150"></div>
                            </div>
                        </div>
                    )}
                    <div ref={messagesEndRef} />
                </div>
            </main>

            {/* Input Area */}
            <footer className="bg-white p-4 border-t border-gray-100">
                <div className="max-w-4xl mx-auto flex flex-col gap-2">
                    {selectedImage && (
                        <div className="relative w-fit">
                            <img src={selectedImage} alt="Selected" className="h-20 w-auto rounded-lg border border-gray-200" />
                            <button
                                onClick={handleRemoveImage}
                                className="absolute -top-2 -right-2 bg-red-500 text-white rounded-full p-1 shadow hover:bg-red-600 transition-colors"
                            >
                                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                            </button>
                        </div>
                    )}
                    <div className="flex gap-2 items-center">
                        <input
                            type="file"
                            accept="image/*"
                            className="hidden"
                            ref={fileInputRef}
                            onChange={handleFileChange}
                        />
                        <button
                            onClick={() => fileInputRef.current?.click()}
                            className="p-3 text-gray-500 hover:text-orange-600 hover:bg-gray-100 rounded-full transition-colors"
                            title="Upload Image"
                        >
                            <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                            </svg>
                        </button>
                        <input
                            type="text"
                            className="flex-1 p-3 border border-gray-300 rounded-full focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent transition-all"
                            placeholder="Ask about indexed content..."
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={handleKeyDown}
                        />
                        <button
                            onClick={sendMessage}
                            disabled={isLoading || (!input.trim() && !selectedImage)}
                            className="bg-gradient-to-r from-orange-500 to-red-500 hover:from-orange-600 hover:to-red-600 disabled:from-orange-300 disabled:to-red-300 text-white p-3 rounded-full shadow-md transition-colors w-12 h-12 flex items-center justify-center"
                        >
                            <svg
                                xmlns="http://www.w3.org/2000/svg"
                                fill="none"
                                viewBox="0 0 24 24"
                                strokeWidth={2}
                                stroke="currentColor"
                                className="w-5 h-5"
                            >
                                <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5"
                                />
                            </svg>
                        </button>
                    </div>
                </div>
            </footer>
        </div>
    );
}
