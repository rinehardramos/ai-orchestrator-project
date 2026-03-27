#!/usr/bin/env python3
"""
Ingest documents into the knowledge base.

Usage:
    python scripts/ingest_document.py <file_path> [--category <cat>] [--tags <tags>]
    python scripts/ingest_document.py --list
    python scripts/ingest_document.py --delete <doc_name>

Examples:
    python scripts/ingest_document.py ~/Downloads/RGRamos_2026.pdf --category resume
    python scripts/ingest_document.py report.docx --category report --tags "quarterly,finance"
    python scripts/ingest_document.py --list
    python scripts/ingest_document.py --delete RGRamos_2026.pdf
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.shared.document_processor import DocumentProcessor
from src.shared.memory.knowledge_store import KnowledgeStore


def main():
    parser = argparse.ArgumentParser(
        description="Ingest documents into the knowledge base",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Ingest a PDF resume:
    python scripts/ingest_document.py ~/Downloads/RGRamos_2026.pdf --category resume

  Ingest with tags:
    python scripts/ingest_document.py report.docx --category report --tags quarterly,finance

  List ingested documents:
    python scripts/ingest_document.py --list

  Delete a document:
    python scripts/ingest_document.py --delete RGRamos_2026.pdf
"""
    )
    parser.add_argument("file", nargs="?", help="File to ingest (PDF, DOCX, TXT, MD)")
    parser.add_argument("--category", default=None, help="Document category (resume, contract, report, notes)")
    parser.add_argument("--tags", default="", help="Comma-separated tags")
    parser.add_argument("--list", action="store_true", help="List ingested documents")
    parser.add_argument("--delete", metavar="DOC_NAME", help="Delete document by name")
    
    args = parser.parse_args()
    
    store = KnowledgeStore()
    
    if args.list:
        docs = store.list_documents()
        if not docs:
            print("No documents in knowledge base.")
            return
        
        print("Ingested documents:\n")
        for doc in docs:
            print(f"  {doc['doc_name']}")
            print(f"    Type: {doc['file_type']}")
            print(f"    Category: {doc.get('category', 'N/A')}")
            print(f"    Chunks: {doc['chunks']}")
            if doc.get('tags'):
                print(f"    Tags: {', '.join(doc['tags'])}")
            print()
        return
    
    if args.delete:
        deleted = store.delete_document(doc_name=args.delete)
        if deleted:
            print(f"Deleted: {args.delete}")
        else:
            print(f"Document not found: {args.delete}")
        return
    
    if not args.file:
        parser.print_help()
        return
    
    file_path = os.path.expanduser(args.file)
    if not os.path.exists(file_path):
        print(f"ERROR: File not found: {file_path}")
        sys.exit(1)
    
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    
    try:
        processor = DocumentProcessor()
        
        print(f"Processing: {os.path.basename(file_path)}")
        
        # Save file to persistent storage
        stored_path = store.save_file(file_path, "cli")
        doc_name = os.path.basename(file_path)
        
        # Process file
        doc_id, chunks = processor.process_file(
            file_path=file_path,
            doc_name=doc_name,
            category=args.category,
            tags=tags,
            source="cli"
        )
        
        # Store in Qdrant
        ingested = store.ingest_document(
            chunks=chunks,
            doc_id=doc_id,
            doc_name=doc_name,
            file_type=processor.get_file_type(file_path),
            source="cli",
            category=args.category,
            tags=tags,
            file_path=stored_path
        )
        
        print(f"\nIngested: {doc_name}")
        print(f"  ID: {doc_id}")
        print(f"  Chunks: {ingested}")
        print(f"  Category: {args.category or 'N/A'}")
        if tags:
            print(f"  Tags: {', '.join(tags)}")
        
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
