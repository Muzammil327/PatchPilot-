"use client";

import { useEffect, useState } from "react";

import { ApiError, fetchRepoMap, type FileMap, type Route } from "@/lib/api";

export interface RepoMapIndex {
  byPath: Map<string, FileMap>;
  routes: Route[];
  testsBySource: Map<string, string[]>;
  sourcesByTest: Map<string, string[]>;
}

export type RepoMapState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; index: RepoMapIndex };

export function useRepoMap(repoId: string): RepoMapState {
  const [state, setState] = useState<RepoMapState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetchRepoMap(repoId, controller.signal)
      .then((repoMap) => {
        const testsBySource = new Map<string, string[]>();
        const sourcesByTest = new Map<string, string[]>();
        for (const link of repoMap.testLinks) {
          sourcesByTest.set(link.testFile, link.sourceFiles);
          for (const source of link.sourceFiles) {
            testsBySource.set(source, [...(testsBySource.get(source) ?? []), link.testFile]);
          }
        }
        setState({
          status: "success",
          index: {
            byPath: new Map(repoMap.files.map((file) => [file.path, file])),
            routes: repoMap.routes,
            testsBySource,
            sourcesByTest,
          },
        });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const message =
          error instanceof ApiError ? error.message : "Could not load the code map.";
        setState({ status: "error", message });
      });
    return () => controller.abort();
  }, [repoId]);

  return state;
}
