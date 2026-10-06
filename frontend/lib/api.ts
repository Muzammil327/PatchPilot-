const DEFAULT_API_BASE_URL = "http://localhost:8000";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL).replace(
  /\/$/,
  "",
);

export interface PromptResponse {
  output: string;
  model: string;
  latencyMs: number;
}

export interface RepoStack {
  language: "typescript" | "javascript" | "unknown";
  frameworks: string[];
  packageManager: string | null;
  scripts: Record<string, string>;
}

export interface RepoFile {
  path: string;
  language: string;
  sizeBytes: number;
}

export interface RepoSummary {
  repoId: string;
  name: string;
  url: string;
  stack: RepoStack;
  fileCount: number;
  skippedCount: number;
  isTruncated: boolean;
  files: RepoFile[];
  functionCount: number;
  classCount: number;
  routeCount: number;
  testFileCount: number;
}

export interface FunctionSymbol {
  name: string;
  line: number;
}

export interface ClassSymbol {
  name: string;
  line: number;
  methods: string[];
}

export interface ImportRef {
  source: string;
  names: string[];
}

export interface FileMap {
  path: string;
  functions: FunctionSymbol[];
  classes: ClassSymbol[];
  imports: ImportRef[];
  exports: string[];
}

export interface Route {
  method: string;
  path: string;
  file: string;
  line: number;
  kind: "page" | "api";
}

export interface TestLink {
  testFile: string;
  sourceFiles: string[];
}

export interface RepoMap {
  files: FileMap[];
  parsedCount: number;
  failedCount: number;
  routes: Route[];
  testLinks: TestLink[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const GENERIC_ERROR_MESSAGE = "Something went wrong. Please try again.";

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof body.detail === "string"
    ) {
      return body.detail;
    }
  } catch {
    // Non-JSON error body: fall through to the generic message.
  }
  return GENERIC_ERROR_MESSAGE;
}

function postJson<TResponse>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<TResponse> {
  return requestJson<TResponse>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}

async function requestJson<TResponse>(path: string, init: RequestInit): Promise<TResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("Cannot reach the PatchPilot backend.", 0);
  }

  if (!response.ok) {
    throw new ApiError(await readErrorMessage(response), response.status);
  }
  return (await response.json()) as TResponse;
}

export function fetchPromptCompletion(
  prompt: string,
  signal?: AbortSignal,
): Promise<PromptResponse> {
  return postJson<PromptResponse>("/api/prompt", { prompt }, signal);
}

export function createRepo(url: string, signal?: AbortSignal): Promise<RepoSummary> {
  return postJson<RepoSummary>("/api/repos", { url }, signal);
}

export function fetchRepo(repoId: string, signal?: AbortSignal): Promise<RepoSummary> {
  return requestJson<RepoSummary>(`/api/repos/${encodeURIComponent(repoId)}`, { signal });
}

export function fetchRepoMap(repoId: string, signal?: AbortSignal): Promise<RepoMap> {
  return requestJson<RepoMap>(`/api/repos/${encodeURIComponent(repoId)}/map`, { signal });
}
