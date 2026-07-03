declare module "pdfjs-dist/build/pdf.mjs" {
  export interface TextItem {
    str: string;
  }

  export interface TextMarkedContent {
    type: string;
  }

  export interface TextContent {
    items: Array<TextItem | TextMarkedContent>;
  }

  export interface PDFPageProxy {
    getTextContent(): Promise<TextContent>;
  }

  export interface PDFDocumentProxy {
    numPages: number;
    getPage(pageNumber: number): Promise<PDFPageProxy>;
    destroy(): Promise<void>;
  }

  export function getDocument(options: {
    data: ArrayBuffer;
    disableWorker?: boolean;
  }): { promise: Promise<PDFDocumentProxy> };
}
