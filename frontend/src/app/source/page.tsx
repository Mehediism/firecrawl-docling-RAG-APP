"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { getSources, addUrlSource, uploadDocument, deleteSource, refreshSource, getSourcePages, getPageContent, Source, Page, PageDetail } from "@/services/api";
import { logger } from "@/utils/logger";

export default function SourcesPage() {
    const [sources, setSources] = useState<Source[]>([]);
    const [total, setTotal] = useState(0);
    const [isLoading, setIsLoading] = useState(true);
    const [urlInput, setUrlInput] = useState("");
    const [isAddingUrl, setIsAddingUrl] = useState(false);
    const [isUploadingDoc, setIsUploadingDoc] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // State for expanded sources and pages
    const [expandedSourceId, setExpandedSourceId] = useState<number | null>(null);
    const [sourcePages, setSourcePages] = useState<{ [key: number]: Page[] }>({});
    const [loadingPages, setLoadingPages] = useState<number | null>(null);

    // State for content modal
    const [selectedPage, setSelectedPage] = useState<PageDetail | null>(null);
    const [loadingContent, setLoadingContent] = useState(false);

    const fetchSources = async () => {
        try {
            const data = await getSources(0, 20);
            setSources(data.items);
            setTotal(data.total);
        } catch (error) {
            logger.error("Failed to fetch sources", error);
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        fetchSources();
        // Poll for updates every 5 seconds
        const interval = setInterval(fetchSources, 5000);
        return () => clearInterval(interval);
    }, []);

    const handleAddUrl = async () => {
        if (!urlInput.trim()) return;

        setIsAddingUrl(true);
        try {
            await addUrlSource(urlInput);
            logger.success("URL added for crawling", { url: urlInput });
            setUrlInput("");
            fetchSources();
        } catch (error) {
            logger.error("Failed to add URL", error);
            alert("Failed to add URL. Please try again.");
        } finally {
            setIsAddingUrl(false);
        }
    };

    const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        setIsUploadingDoc(true);
        try {
            await uploadDocument(file);
            logger.success("Document uploaded for parsing", { filename: file.name });
            fetchSources();
        } catch (error) {
            logger.error("Failed to upload document", error);
            alert("Failed to upload document. Please try again.");
        } finally {
            setIsUploadingDoc(false);
            if (fileInputRef.current) fileInputRef.current.value = "";
        }
    };

    const handleDelete = async (id: number) => {
        if (!confirm("Are you sure you want to delete this source?")) return;

        try {
            await deleteSource(id);
            logger.success("Source deleted", { id });
            fetchSources();
        } catch (error) {
            logger.error("Failed to delete source", error);
        }
    };

    const handleRefresh = async (id: number) => {
        try {
            await refreshSource(id);
            logger.success("Source refresh started", { id });
            fetchSources();
        } catch (error) {
            logger.error("Failed to refresh source", error);
        }
    };

    const handleToggleExpand = async (sourceId: number) => {
        if (expandedSourceId === sourceId) {
            setExpandedSourceId(null);
            return;
        }

        setExpandedSourceId(sourceId);

        // Fetch pages if not already loaded
        if (!sourcePages[sourceId]) {
            setLoadingPages(sourceId);
            try {
                const data = await getSourcePages(sourceId);
                setSourcePages((prev) => ({ ...prev, [sourceId]: data.items }));
            } catch (error) {
                logger.error("Failed to fetch pages", error);
            } finally {
                setLoadingPages(null);
            }
        }
    };

    const handleViewContent = async (pageId: number) => {
        setLoadingContent(true);
        try {
            const page = await getPageContent(pageId);
            setSelectedPage(page);
        } catch (error) {
            logger.error("Failed to fetch page content", error);
            alert("Failed to load page content.");
        } finally {
            setLoadingContent(false);
        }
    };

    const getStatusColor = (status: string) => {
        switch (status) {
            case "processed": return "bg-green-100 text-green-800";
            case "processing": return "bg-yellow-100 text-yellow-800";
            case "pending": return "bg-blue-100 text-blue-800";
            case "failed": return "bg-red-100 text-red-800";
            case "empty": return "bg-gray-100 text-gray-800";
            default: return "bg-gray-100 text-gray-800";
        }
    };

    const getTypeIcon = (type: string) => {
        if (type === "web_url") {
            return (
                <svg className="w-5 h-5 text-orange-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
                </svg>
            );
        }
        return (
            <svg className="w-5 h-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
        );
    };

    return (
        <div className="min-h-screen bg-gray-50">
            {/* Header */}
            <header className="bg-white shadow-sm p-4 sticky top-0 z-10">
                <div className="max-w-6xl mx-auto flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 bg-gradient-to-r from-orange-500 to-red-500 rounded-full flex items-center justify-center text-white font-bold text-xl">
                            🔥
                        </div>
                        <h1 className="text-xl font-bold text-gray-900">Source Management</h1>
                    </div>
                    <Link
                        href="/"
                        className="px-4 py-2 bg-gradient-to-r from-orange-500 to-red-500 text-white rounded-lg hover:from-orange-600 hover:to-red-600 transition-colors"
                    >
                        Back to Chat
                    </Link>
                </div>
            </header>

            <main className="max-w-6xl mx-auto p-6">
                {/* Add Sources Section */}
                <div className="bg-white rounded-xl shadow-sm p-6 mb-6">
                    <h2 className="text-lg font-semibold mb-4">Add New Source</h2>

                    <div className="grid md:grid-cols-2 gap-6">
                        {/* URL Input */}
                        <div className="space-y-3">
                            <label className="block text-sm font-medium text-gray-700">
                                🔥 Add URL (Firecrawl)
                            </label>
                            <div className="flex gap-2">
                                <input
                                    type="url"
                                    placeholder="https://example.com"
                                    value={urlInput}
                                    onChange={(e) => setUrlInput(e.target.value)}
                                    className="flex-1 p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                                />
                                <button
                                    onClick={handleAddUrl}
                                    disabled={isAddingUrl || !urlInput.trim()}
                                    className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 disabled:bg-orange-300 transition-colors"
                                >
                                    {isAddingUrl ? "Adding..." : "Crawl"}
                                </button>
                            </div>
                            <p className="text-xs text-gray-500">
                                Firecrawl will automatically discover and index all pages on the website.
                            </p>
                        </div>

                        {/* Document Upload */}
                        <div className="space-y-3">
                            <label className="block text-sm font-medium text-gray-700">
                                📄 Upload Document (Docling)
                            </label>
                            <div className="flex gap-2">
                                <input
                                    type="file"
                                    ref={fileInputRef}
                                    accept=".pdf,.png,.jpg,.jpeg,.tiff,.bmp"
                                    onChange={handleFileUpload}
                                    className="hidden"
                                />
                                <button
                                    onClick={() => fileInputRef.current?.click()}
                                    disabled={isUploadingDoc}
                                    className="flex-1 p-3 border-2 border-dashed border-gray-300 rounded-lg hover:border-orange-500 hover:bg-orange-50 transition-colors text-gray-600"
                                >
                                    {isUploadingDoc ? "Uploading..." : "Click to upload PDF or Image"}
                                </button>
                            </div>
                            <p className="text-xs text-gray-500">
                                Docling uses AI for layout analysis and table recognition.
                            </p>
                        </div>
                    </div>
                </div>

                {/* Sources List */}
                <div className="bg-white rounded-xl shadow-sm p-6">
                    <div className="flex justify-between items-center mb-4">
                        <h2 className="text-lg font-semibold">Indexed Sources ({total})</h2>
                    </div>

                    {isLoading ? (
                        <div className="text-center py-8 text-gray-500">Loading sources...</div>
                    ) : sources.length === 0 ? (
                        <div className="text-center py-8 text-gray-500">
                            No sources indexed yet. Add a URL or upload a document to get started.
                        </div>
                    ) : (
                        <div className="space-y-3">
                            {sources.map((source) => (
                                <div key={source.id} className="border border-gray-200 rounded-lg overflow-hidden">
                                    {/* Source Header */}
                                    <div
                                        className={`flex items-center gap-4 p-4 bg-gray-50 cursor-pointer hover:bg-gray-100 transition-colors ${expandedSourceId === source.id ? 'bg-orange-50' : ''}`}
                                        onClick={() => source.type === "web_url" && source.page_count > 0 && handleToggleExpand(source.id)}
                                    >
                                        {getTypeIcon(source.type)}

                                        <div className="flex-1 min-w-0">
                                            <p className="font-medium text-gray-900 truncate">{source.source_name}</p>
                                            <div className="flex items-center gap-2 mt-1">
                                                <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${getStatusColor(source.status)}`}>
                                                    {source.status}
                                                </span>
                                                <span className="text-xs text-gray-500">
                                                    {source.type === "web_url" ? "Firecrawl" : "Docling"}
                                                </span>
                                                {source.type === "web_url" && source.page_count > 0 && (
                                                    <span className="text-xs text-blue-600 font-medium">
                                                        {source.page_count} pages
                                                    </span>
                                                )}
                                            </div>
                                            {source.error && (
                                                <p className="text-xs text-red-500 mt-1 truncate">{source.error}</p>
                                            )}
                                        </div>

                                        {/* Expand Arrow */}
                                        {source.type === "web_url" && source.page_count > 0 && (
                                            <svg
                                                className={`w-5 h-5 text-gray-400 transition-transform ${expandedSourceId === source.id ? 'rotate-180' : ''}`}
                                                fill="none"
                                                viewBox="0 0 24 24"
                                                stroke="currentColor"
                                            >
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                            </svg>
                                        )}

                                        <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
                                            <button
                                                onClick={() => handleRefresh(source.id)}
                                                className="p-2 text-gray-500 hover:text-orange-600 hover:bg-orange-50 rounded-lg transition-colors"
                                                title="Refresh"
                                            >
                                                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                                                </svg>
                                            </button>
                                            <button
                                                onClick={() => handleDelete(source.id)}
                                                className="p-2 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                                                title="Delete"
                                            >
                                                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                                </svg>
                                            </button>
                                        </div>
                                    </div>

                                    {/* Expanded Pages List */}
                                    {expandedSourceId === source.id && (
                                        <div className="border-t border-gray-200 bg-white">
                                            {loadingPages === source.id ? (
                                                <div className="p-4 text-center text-gray-500">Loading pages...</div>
                                            ) : sourcePages[source.id]?.length > 0 ? (
                                                <ul className="divide-y divide-gray-100">
                                                    {sourcePages[source.id].map((page) => (
                                                        <li
                                                            key={page.id}
                                                            className="p-3 pl-12 hover:bg-orange-50 cursor-pointer flex items-center gap-3 transition-colors"
                                                            onClick={() => handleViewContent(page.id)}
                                                        >
                                                            <svg className="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                                            </svg>
                                                            <div className="flex-1 min-w-0">
                                                                <p className="text-sm font-medium text-gray-800 truncate">
                                                                    {page.page_title || page.page_url}
                                                                </p>
                                                                <p className="text-xs text-gray-500 truncate">{page.page_url}</p>
                                                            </div>
                                                            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${getStatusColor(page.status)}`}>
                                                                {page.status}
                                                            </span>
                                                            <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                                            </svg>
                                                        </li>
                                                    ))}
                                                </ul>
                                            ) : (
                                                <div className="p-4 text-center text-gray-500">No pages found.</div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </main>

            {/* Content Modal */}
            {selectedPage && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
                    <div className="bg-white rounded-xl shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
                        {/* Modal Header */}
                        <div className="p-4 border-b border-gray-200 flex items-center justify-between bg-gray-50">
                            <div className="min-w-0 flex-1">
                                <h3 className="text-lg font-semibold text-gray-900 truncate">
                                    {selectedPage.page_title || "Page Content"}
                                </h3>
                                <a
                                    href={selectedPage.page_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-sm text-blue-600 hover:underline truncate block"
                                >
                                    {selectedPage.page_url}
                                </a>
                            </div>
                            <button
                                onClick={() => setSelectedPage(null)}
                                className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors ml-4"
                            >
                                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                            </button>
                        </div>

                        {/* Modal Content */}
                        <div className="p-6 overflow-y-auto flex-1">
                            {loadingContent ? (
                                <div className="text-center text-gray-500">Loading content...</div>
                            ) : (
                                <div className="prose prose-sm max-w-none whitespace-pre-wrap text-gray-700">
                                    {selectedPage.content}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
