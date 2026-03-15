import { API_BASE_URL } from "@/config";

export interface ChatResponse {
    response: string;
}

export interface Source {
    id: number;
    source_name: string;
    type: string;
    status: string;
    error?: string;
    last_updated?: string;
    page_count: number;
}

export interface SourceListResponse {
    total: number;
    items: Source[];
}

export interface Page {
    id: number;
    page_url: string;
    page_title?: string;
    status: string;
    last_updated?: string;
}

export interface PageDetail extends Page {
    content: string;
}

export interface PageListResponse {
    total: number;
    items: Page[];
}

export const sendChatMessage = async (message: string, thread_id: string, image?: string): Promise<ChatResponse> => {
    const response = await fetch(`${API_BASE_URL}/chat`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ message, image, thread_id }),
    });

    if (!response.ok) {
        throw new Error("Failed to fetch response");
    }

    return response.json();
};

// Ingestion API functions
export const addUrlSource = async (url: string): Promise<{ message: string; id: number }> => {
    const response = await fetch(`${API_BASE_URL}/ingestion/add`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ url }),
    });

    if (!response.ok) {
        throw new Error("Failed to add URL");
    }

    return response.json();
};

export const uploadDocument = async (file: File): Promise<{ message: string; id: number }> => {
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(`${API_BASE_URL}/ingestion/add-document`, {
        method: "POST",
        body: formData,
    });

    if (!response.ok) {
        throw new Error("Failed to upload document");
    }

    return response.json();
};

export const getSources = async (skip: number = 0, limit: number = 10): Promise<SourceListResponse> => {
    const response = await fetch(`${API_BASE_URL}/ingestion/list?skip=${skip}&limit=${limit}`);

    if (!response.ok) {
        throw new Error("Failed to fetch sources");
    }

    return response.json();
};

export const getSourcePages = async (sourceId: number): Promise<PageListResponse> => {
    const response = await fetch(`${API_BASE_URL}/ingestion/${sourceId}/pages`);

    if (!response.ok) {
        throw new Error("Failed to fetch pages");
    }

    return response.json();
};

export const getPageContent = async (pageId: number): Promise<PageDetail> => {
    const response = await fetch(`${API_BASE_URL}/ingestion/pages/${pageId}`);

    if (!response.ok) {
        throw new Error("Failed to fetch page content");
    }

    return response.json();
};

export const deleteSource = async (id: number): Promise<{ message: string }> => {
    const response = await fetch(`${API_BASE_URL}/ingestion/delete/${id}`, {
        method: "DELETE",
    });

    if (!response.ok) {
        throw new Error("Failed to delete source");
    }

    return response.json();
};

export const refreshSource = async (id: number): Promise<{ message: string }> => {
    const response = await fetch(`${API_BASE_URL}/ingestion/refresh/${id}`, {
        method: "PUT",
    });

    if (!response.ok) {
        throw new Error("Failed to refresh source");
    }

    return response.json();
};

