
REPO_URL = "https://github.com/prasanna192005/DSA-Auto.git"

# config.py


BELT_SYLLABUS = {
    "White Belt": {
        "Programming Basics": ["Input/Output", "Variables & Data Types", "Operators (Arithmetic, Relational, Logical)", "Bitwise Operators", "Type Casting"],
        "Control Flow": ["Conditionals (if-else, switch-case)", "Loops (for, while)", "Break & Continue"],
        "Functions": ["Function Definition & Call", "Parameters & Arguments", "Return Values", "Intro to Recursion (factorial)"],
        "Arrays": ["1D Array Declaration & Traversal", "Basic Array Operations (sum, max, min)"],
        "Strings": ["Basic String Manipulation", "Palindrome Check", "String Reversal"],
        "Complexity": ["Intro to Time & Space Complexity", "Best/Worst/Average Case Basics"],
        "Math Foundations": ["Modulo Arithmetic", "Prime Check", "GCD/LCM"]
    },
    "Yellow Belt": {
        "Arrays (Advanced)": ["2D Arrays / Matrix Operations", "Prefix & Suffix Sums", "Kadane’s Algorithm", "Sliding Window Intro"],
        "Strings (Intermediate)": ["Naive Pattern Search", "Frequency Count / Anagrams"],
        "Recursion": ["Recursive Power Function", "Recursive Fibonacci", "Intro to Backtracking"],
        "Linked Lists": ["Singly Linked List (creation, traversal, insertion, deletion)", "Doubly Linked List basics"],
        "Stacks": ["Stack Implementation (Array/LL)", "Infix to Postfix Conversion", "Balanced Brackets Problem"],
        "Queues": ["Queue Implementation (Array/LL)", "Circular Queue basics"],
        "Searching & Sorting (Intro)": ["Linear Search", "Binary Search (Iterative & Recursive)", "Selection Sort", "Bubble Sort", "Insertion Sort"]
    },
    "Orange Belt": {
        "Sorting (Advanced)": ["Merge Sort", "Quick Sort", "Heap Sort", "Counting Sort"],
        "Searching (Advanced)": ["Binary Search on Answer (Aggressive Cows, Book Allocation)", "First/Last Occurrence of an Element"],
        "Stacks & Queues (Advanced)": ["Next Greater/Smaller Element (Monotonic Stack)", "Sliding Window Maximum (Deque)"],
        "Hashing": ["Hash Tables & Hash Maps", "Collision Handling Introduction"],
        "Recursion & Backtracking": ["Generate all Subsets", "Generate all Permutations", "Rat in a Maze"],
        "Linked List (Advanced)": ["Cycle Detection (Fast/Slow Pointers)", "Reverse a Linked List", "Merge Two Sorted Lists"]
    },
    "Red Belt": {
        "Binary Trees": ["Tree Definition & Properties", "Tree Traversals (Preorder, Inorder, Postorder)", "Level Order Traversal (BFS)", "Height and Diameter of a Tree"],
        "Binary Search Trees (BSTs)": ["BST Insertion, Deletion, Search", "Validate a BST", "Lowest Common Ancestor in BST"],
        "Heaps & Priority Queues": ["Min-Heap & Max-Heap", "Heapify Algorithm", "Using Priority Queues for K-th largest element"],
        "Recursion & Backtracking (Advanced)": ["N-Queens Problem", "Sudoku Solver", "Word Search Problem"],
        "Mathematics": ["Divide & Conquer Strategy", "Basic Recurrence Relations"],
        "Complexity (Deeper)": ["Intro to Master Theorem for analyzing recursive calls"]
    },
    "Green Belt": {
        "Graph Representation": ["Adjacency Matrix", "Adjacency List"],
        "Graph Traversals": ["Breadth-First Search (BFS)", "Depth-First Search (DFS)", "Connected Components"],
        "Graph Applications": ["Bipartite Graph Check", "Cycle Detection in Graphs"],
        "Union-Find (DSU)": ["Find & Union Operations", "Path Compression"],
        "Greedy Algorithms": ["Activity Selection Problem", "Interval Scheduling"],
        "Dynamic Programming (Intro)": ["Fibonacci (Memoization vs Tabulation)", "0/1 Knapsack basics", "Longest Common Subsequence (LCS) intro"]
    },
    "Blue Belt": {
        "Graph Algorithms (Weighted)": ["Dijkstra’s Shortest Path Algorithm", "Bellman-Ford Algorithm", "Floyd-Warshall Algorithm"],
        "Minimum Spanning Tree (MST)": ["Kruskal’s Algorithm", "Prim’s Algorithm"],
        "Dynamic Programming (Intermediate)": ["Matrix Chain Multiplication", "Coin Change Problem", "Subset Sum Problem", "Longest Increasing Subsequence (LIS)"],
        "Advanced Data Structures": ["Segment Tree (Range Sum Queries)", "Fenwick Tree (Binary Indexed Tree)", "Trie for string prefix search"],
        "Greedy Algorithms (Advanced)": ["Huffman Coding", "Job Scheduling with Deadlines"],
        "Mathematics": ["Modular Exponentiation (Fast Power)", "Extended Euclidean Algorithm"]
    },
    "Purple Belt": {
        "Graphs (Advanced)": ["Strongly Connected Components (Kosaraju's Algorithm)", "Bridges & Articulation Points", "Euler Tour"],
        "Dynamic Programming (Advanced)": ["DP on Trees", "DP with Bitmasking", "Digit DP"],
        "String Algorithms": ["KMP Algorithm", "Z-Algorithm", "Rabin-Karp Algorithm", "Suffix Arrays intro"],
        "Geometry Algorithms": ["Convex Hull (Graham Scan)", "Line Sweeping basics"],
        "Game Theory": ["Grundy Numbers / Nim Game"],
        "Bit Manipulation (Advanced)": ["Generating Subsets with Bitmask", "Advanced XOR properties"]
    }
}