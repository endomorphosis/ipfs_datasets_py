
from typing import Any
import hashlib

class Node:
    def __init__(self, left, right, value: str, content: Any, is_copied: bool = False) -> None:
        self.left: Node = left
        self.right: Node = right
        self.value = value
        self.content = content
        self.is_copied = is_copied

    @staticmethod
    def hash(val: str) -> str:
        return hashlib.sha256(val.encode('utf-8')).hexdigest()

    def __str__(self):
        return (str(self.value))

    def copy(self):
        """
        class copy function
        """
        return Node(self.left, self.right, self.value, self.content, True)


class MerkleTree:
    """
    Code by Pranay Arora (TSEC-2023).
    See: https://www.geeksforgeeks.org/introduction-to-merkle-tree/

    Example:
        elems = ["GeeksforGeeks", "A", "Computer",
                "Science", "Portal", "For", "Geeks"]

        # As there are odd number of inputs, the last input is repeated
        print("Inputs: ")
        print(*elems, sep=" | ")
        print("")
        mtree = MerkleTree(elems)
        print("Root Hash: " + mtree.get_root_hash() + "\n")
        mtree.print_tree()
    """

    def __init__(self, values: list[str]) -> None:
        self._build_tree(values)


    def _build_tree(self, values: list[str]) -> None:

        leaves: list[Node] = [
            Node(None, None, Node.hash(v), v) for v in values
        ]

        if len(leaves) % 2 == 1:
            # duplicate last elem if odd number of elements
            leaves.append(leaves[-1].copy())

        self.root: Node = self._build_tree_rec(leaves)


    def _build_tree_rec(self, nodes: list[Node]) -> Node:

        if len(nodes) % 2 == 1:
            # duplicate last elem if odd number of elements
            nodes.append(nodes[-1].copy())

        half: int = len(nodes) // 2

        if len(nodes) == 2:
            return Node(
                nodes[0], 
                nodes[1], 
                Node.hash(nodes[0].value + nodes[1].value), 
                nodes[0].content+"+"+nodes[1].content
            )

        left: Node = self._build_tree_rec(nodes[:half])
        right: Node = self._build_tree_rec(nodes[half:])
        value: str = Node.hash(left.value + right.value)
        content: str = f'{left.content}+{right.content}'

        return Node(left, right, value, content)


    def print_tree(self) -> None:
        self._print_tree_rec(self.root)


    def _print_tree_rec(self, node: Node) -> None:

        if node != None:
            if node.left != None:
                print("Left: " + str(node.left))
                print("Right: " + str(node.right))
            else:
                print("Input")

            if node.is_copied:
                print('(Padding)')

            print("Value: " + str(node.value))
            print("Content: " + str(node.content))
            print("")
            self._print_tree_rec(node.left)
            self._print_tree_rec(node.right)


    def get_root_hash(self) -> str:
        return self.root.value
