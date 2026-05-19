"""Hint content generation service.

Generates tiered hint content for problems based on their tags and difficulty.
Each level provides progressively more specific guidance:

- Level 1: Algorithm direction / category hint
- Level 2: Specific method / key state definition
- Level 3: Near-complete solution approach
"""

import logging
import random

logger = logging.getLogger("code_arena.hints")

# ---------------------------------------------------------------------------
# Tag-to-hint mapping
# ---------------------------------------------------------------------------

_TAG_HINTS: dict[str, dict[str, list[str]]] = {
    "dp": {
        1: [
            "Consider using dynamic programming to break "
            "this problem into overlapping subproblems.",
            "Think about defining a state that captures the "
            "essential information at each step.",
            "This is a DP problem -- try to identify the "
            "recurrence relation.",
        ],
        2: [
            "Define dp[i] as the optimal value for the first i "
            "elements. Think about valid transitions.",
            "Consider a 2D DP table where one dimension is position "
            "and the other is a constraint.",
            "Try bottom-up DP. What are the base cases and how does "
            "each state depend on previous ones?",
        ],
        3: [
            "Initialize dp[0] as base case. For each i from 1 to n, "
            "dp[i] = min/max of valid transitions from dp[j] (j<i).",
            "Use DP: dp[i][j] = optimal for subproblem with params "
            "i and j. Transition by considering each choice.",
            "Classic interval DP. Define dp[l][r] for range [l, r]. "
            "Compute in order of increasing interval length.",
        ],
    },
    "greedy": {
        1: [
            "Try a greedy approach -- make the locally optimal "
            "choice at each step.",
            "This problem might have a greedy solution where "
            "sorting helps.",
            "Consider whether always picking the best immediate "
            "option leads to the global optimum.",
        ],
        2: [
            "Sort the items first, then greedily select in order. "
            "Track the running constraint.",
            "The greedy choice: always pick the option that "
            "maximizes/minimizes the key metric.",
            "Try processing elements in sorted order and "
            "maintaining a running result.",
        ],
        3: [
            "Sort by the key criterion. Iterate and decide for each "
            "whether to include based on current best answer. "
            "Use a priority queue for efficient candidate management.",
            "Sort elements by one property and greedily pair by "
            "another. Correctness relies on exchange argument.",
        ],
    },
    "math": {
        1: [
            "This problem requires mathematical insight. "
            "Look for patterns or formulas.",
            "Think about modular arithmetic and number properties.",
            "Try to find a mathematical formula or closed-form "
            "solution rather than brute force.",
        ],
        2: [
            "Compute using modular arithmetic. Key ops: "
            "(a + b) % mod, (a * b) % mod.",
            "Find a pattern via small cases. Likely involves "
            "gcd, lcm, or prime factorization.",
            "Use inclusion-exclusion or combinatorics to count "
            "the answer efficiently.",
        ],
        3: [
            "Use fast exponentiation with modulo for large powers. "
            "Handle edge cases n=0 or n=1 separately.",
            "Apply: result = pow(base, exp, mod) * coeff % mod. "
            "Precompute factorials for combinatorics.",
        ],
    },
    "graphs": {
        1: [
            "Model this as a graph problem. Think about BFS, DFS, "
            "or shortest paths.",
            "Consider representing the data as a graph and "
            "applying traversal algorithms.",
            "This is a graph theory problem -- think about "
            "connected components or paths.",
        ],
        2: [
            "Use BFS to find shortest paths from the source. "
            "Track distances in an array.",
            "Build adjacency list and run Dijkstra's algorithm "
            "for weighted shortest paths.",
            "Use topological sorting for DAGs, or DFS for "
            "cycle detection.",
        ],
        3: [
            "Build adjacency list. Run BFS from source with "
            "distance array init to infinity. Update when shorter "
            "path found. Answer = distance to target.",
            "Construct graph and run Dijkstra with priority queue. "
            "dist[source] = 0, process nodes by increasing distance.",
        ],
    },
    "strings": {
        1: [
            "Think about string matching or pattern techniques "
            "like hashing or KMP.",
            "Consider processing the string character by character "
            "with a state machine.",
            "Look for palindromic properties or use a "
            "two-pointer approach.",
        ],
        2: [
            "Use string hashing to compare substrings in O(1). "
            "Precompute prefix hashes.",
            "Try two-pointer: one from left, one from right.",
            "Build a suffix array or use Z-function for "
            "string matching.",
        ],
        3: [
            "Precompute polynomial rolling hashes for prefixes. "
            "Compare substrings via hash formula. "
            "Use two moduli to avoid collisions.",
            "Use Manacher's algorithm for palindromes: compute "
            "odd/even radii in O(n). Or Z-function for patterns.",
        ],
    },
    "data structures": {
        1: [
            "Consider an efficient data structure like segment "
            "tree, heap, or balanced BST.",
            "Think about what queries you need to support and "
            "choose the right data structure.",
            "This likely requires a data structure that supports "
            "fast range queries or updates.",
        ],
        2: [
            "A segment tree with lazy propagation handles range "
            "updates and queries in O(log n).",
            "Use union-find (disjoint set union) to manage "
            "connected components efficiently.",
            "Consider a monotonic stack or deque for this problem.",
        ],
        3: [
            "Build a segment tree where each node stores aggregate "
            "for its range. Lazy propagation for updates. "
            "Combine O(log n) nodes for queries.",
            "Use DSU with path compression and union by rank. "
            "Path compression during find makes ops nearly O(1).",
        ],
    },
    "binary search": {
        1: [
            "This problem can be solved with binary search "
            "on the answer.",
            "Think about whether the search space is monotonic "
            "-- if so, binary search applies.",
            "Consider binary search to efficiently narrow down "
            "the solution space.",
        ],
        2: [
            "Binary search on the answer. Define a check function "
            "that returns True if candidate is feasible.",
            "Use binary search: if f(mid) is True, search left; "
            "otherwise search right.",
            "Apply binary search on sorted array or answer space "
            "with a monotonic predicate.",
        ],
        3: [
            "Set lo/hi to bracket answer. While lo < hi: "
            "mid = (lo+hi)/2. If check(mid): hi=mid, else lo=mid+1. "
            "Answer is lo.",
            "Binary search on answer. check() greedily verifies "
            "candidate by scanning. Time: O(n log(range)).",
        ],
    },
    "sortings": {
        1: [
            "Sorting the data first might reveal the solution.",
            "Consider whether sorting by a specific criterion "
            "simplifies the problem.",
            "Try sorting and then processing elements in order.",
        ],
        2: [
            "Sort by one key and scan through to find the answer.",
            "Use coordinate compression if values are large but "
            "relative order matters.",
            "After sorting, use two pointers or binary search "
            "for each element.",
        ],
        3: [
            "Sort by primary key. Use sweep line or two-pointer: "
            "for each element, find match via binary search or "
            "running window.",
            "Apply coordinate compression. After sorting, use "
            "Fenwick tree for inversions or frequency tracking.",
        ],
    },
    "constructive algorithms": {
        1: [
            "Try constructing the answer directly with a "
            "clear pattern.",
            "Think about what a valid solution looks like and "
            "work backwards.",
            "Consider a constructive approach: build the answer "
            "step by step.",
        ],
        2: [
            "Start with simple construction and refine. Pattern "
            "often involves alternating or pairing elements.",
            "Think about parity or symmetry to construct "
            "a valid solution.",
            "Construction usually involves placing elements in "
            "specific order to satisfy all constraints.",
        ],
        3: [
            "Construct by placing all elements of one type first, "
            "then filling gaps with another. Verify each constraint.",
            "Arrange elements by property X, assign value per "
            "formula. Key insight: arrangement guarantees "
            "all constraints.",
        ],
    },
    "number theory": {
        1: [
            "This involves number theory concepts like primes, "
            "gcd, or modular arithmetic.",
            "Think about prime factorization or properties "
            "of divisors.",
            "Consider using Sieve of Eratosthenes or Euler's "
            "totient function.",
        ],
        2: [
            "Compute gcd/lcm via Euclid's algorithm. For multiple "
            "numbers, reduce iteratively.",
            "Use extended Euclidean algorithm for modular inverses.",
            "Factorize and use prime factorization to compute "
            "the answer.",
        ],
        3: [
            "Precompute smallest prime factor (SPF) up to max_n "
            "via modified sieve. Factorize by repeatedly "
            "dividing by SPF[n].",
            "Use formula: gcd(a,b) * lcm(a,b) = a * b. "
            "Modular inverse via Fermat: a^(-1) = a^(p-2) mod p.",
        ],
    },
    "trees": {
        1: [
            "This is a tree problem. Consider DFS from root "
            "or using tree properties.",
            "Think about tree DP: compute answers for subtrees "
            "bottom-up.",
            "Trees have unique paths between any two nodes "
            "-- leverage this property.",
        ],
        2: [
            "Use DFS to compute subtree sizes. Many tree problems "
            "reduce to aggregating subtree info.",
            "Tree diameter can be found with two BFS calls, "
            "or with tree DP.",
            "Consider LCA (Lowest Common Ancestor) for path "
            "queries on trees.",
        ],
        3: [
            "Root at node 1. DFS to compute dp[u] for each node: "
            "aggregate of dp[v] for children v. "
            "Answer is root's dp or max/min across all nodes.",
            "Use Euler tour to flatten tree into array. "
            "Segment tree on Euler tour for subtree/path queries. "
            "LCA via sparse table.",
        ],
    },
    "geometry": {
        1: [
            "Computational geometry problem. Think about "
            "coordinates and geometric properties.",
            "Consider cross products for orientation tests "
            "and area calculations.",
            "Look for geometric properties like convex hull, "
            "line intersections, or distance formulas.",
        ],
        2: [
            "Use cross product to determine orientation "
            "(CW, CCW, collinear).",
            "Compute convex hull using Andrew's monotone "
            "chain algorithm.",
            "For intersection checks, use parametric "
            "line representation.",
        ],
        3: [
            "Sort points by x then y. Build upper/lower hulls "
            "via stack: pop on non-left turn. Merge hulls.",
            "Use cross product for point-in-polygon via signed "
            "triangle areas. Or ray casting for general queries.",
        ],
    },
}

# Fallback hints for tags not in the mapping
_FALLBACK_HINTS: dict[int, list[str]] = {
    1: [
        "Try to identify the key pattern or property "
        "in this problem.",
        "Break the problem down into smaller subproblems.",
        "Consider whether greedy, DP, or divide-and-conquer "
        "approach works.",
    ],
    2: [
        "Define the state carefully and think about valid "
        "transitions between states.",
        "Process elements in specific order and maintain "
        "a running result.",
        "Look for a pattern by working through small examples.",
    ],
    3: [
        "Process each element, update state, track optimal. "
        "Handle first/last edge cases separately.",
        "Precompute needed values, iterate main structure "
        "while maintaining state. Answer from final state.",
    ],
}

# Rating-based difficulty descriptions
_RATING_DESCRIPTIONS: list[tuple[int, str]] = [
    (1100, "an introductory"),
    (1400, "an intermediate"),
    (1700, "a moderately difficult"),
    (2000, "a challenging"),
    (9999, "an advanced"),
]


def _get_difficulty_label(rating: int) -> str:
    """Return a difficulty description based on problem rating."""
    for threshold, label in _RATING_DESCRIPTIONS:
        if rating < threshold:
            return label
    return "an advanced"


class HintContentService:
    """Generates hint content for problems based on tags and difficulty."""

    @staticmethod
    def generate_hint(
        problem_id: str,
        problem_rating: int,
        tags: list[str],
        level: int,
    ) -> str:
        """Generate a hint for the given problem at the specified level.

        Parameters
        ----------
        problem_id : str
            CF problem ID (e.g. "1234A").
        problem_rating : int
            Problem difficulty rating.
        tags : list[str]
            CF problem tags.
        level : int
            Hint level (1, 2, or 3).

        Returns
        -------
        str
            Generated hint content.
        """
        difficulty = _get_difficulty_label(problem_rating)

        # Try to find a matching tag
        for tag in tags:
            tag_lower = tag.lower().replace(" ", "_")
            if tag_lower in _TAG_HINTS:
                hints = _TAG_HINTS[tag_lower].get(level, [])
                if hints:
                    chosen = random.choice(hints)
                    return f"[{difficulty} problem] {chosen}"

        # Fallback to generic hints
        fallback = _FALLBACK_HINTS.get(level, [])
        if fallback:
            chosen = random.choice(fallback)
            return f"[{difficulty} problem] {chosen}"

        return (
            f"[{difficulty} problem] Consider different algorithmic "
            "approaches and work through small examples."
        )
