from duckduckgo_search import DDGS

try:
    with DDGS() as ddgs:
        results = list(ddgs.text("Flux.1 image model", max_results=5))
        print("Results length:", len(results))
        if results:
            print("First:", results[0])
except Exception as e:
    print("Error:", e)
