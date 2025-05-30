"""
IPLD DAG-PB Module

Provides functions for working with the DAG-PB (Protobuf DAG) format,
which is the primary data structure used in IPFS.
"""

import io
import struct
from typing import Dict, List, Optional, Tuple, Union, Any, Set, Callable

try:
    from multiformats import CID
    HAVE_MULTIFORMATS = True
except ImportError:
    HAVE_MULTIFORMATS = False
    # Simple CID class for compatibility
    class CID:
        @staticmethod
        def decode(cid_str):
            return cid_str

        @staticmethod
        def encode(cid_obj):
            return str(cid_obj)

try:
    # Try to import the official py-ipld-dag-pb if available
    from ipld_dag_pb import encode, decode, PBNode, PBLink
    HAVE_IPLD_DAG_PB = True
except ImportError:
    HAVE_IPLD_DAG_PB = False


# If the official library is not available, provide basic protobuf encoding/decoding
# Note: This is a simplified implementation for demonstration purposes
if not HAVE_IPLD_DAG_PB:
    def encode_varint(value):
        """Encode an integer as a protobuf varint."""
        buf = bytearray()
        while True:
            byte = value & 0x7f
            value >>= 7
            if value:
                byte |= 0x80
            buf.append(byte)
            if not value:
                break
        return bytes(buf)

    def decode_varint(buf, pos):
        """Decode a protobuf varint to an integer."""
        result = 0
        shift = 0
        while True:
            byte = buf[pos]
            pos += 1
            result |= ((byte & 0x7f) << shift)
            if not (byte & 0x80):
                break
            shift += 7
        return result, pos

    def encode_field(field_num, wire_type, value):
        """Encode a protobuf field."""
        tag = (field_num << 3) | wire_type
        return encode_varint(tag) + value

    def encode_bytes(value):
        """Encode bytes as a protobuf bytes field."""
        return encode_varint(len(value)) + value

    class PBLink:
        """A link in a DAG-PB node."""

        def __init__(self, name=None, cid=None, tsize=None):
            self.name = name
            self.cid = cid
            self.tsize = tsize

        def to_dict(self):
            """Convert to a dictionary representation."""
            result = {}
            if self.name is not None:
                result["Name"] = self.name
            if self.cid is not None:
                result["Hash"] = self.cid
            if self.tsize is not None:
                result["Tsize"] = self.tsize
            return result

        @classmethod
        def from_dict(cls, obj):
            """Create a PBLink from a dictionary."""
            return cls(
                name=obj.get("Name"),
                cid=obj.get("Hash"),
                tsize=obj.get("Tsize")
            )

    class PBNode:
        """A node in a DAG-PB graph."""

        def __init__(self, data=None, links=None):
            self.data = data
            self.links = links or []

        def to_dict(self):
            """Convert to a dictionary representation."""
            result = {}
            if self.data is not None:
                result["Data"] = self.data
            if self.links:
                result["Links"] = [link.to_dict() for link in self.links]
            return result

        @classmethod
        def from_dict(cls, obj):
            """Create a PBNode from a dictionary."""
            links = [PBLink.from_dict(link) for link in obj.get("Links", [])]
            return cls(
                data=obj.get("Data"),
                links=links
            )

    def encode(node):
        """Encode a PBNode as a protobuf message."""
        buf = bytearray()

        # Encode links (field 1, repeated message)
        for link in node.links:
            link_buf = bytearray()

            # Name (field 1, string)
            if link.name is not None:
                name_bytes = link.name.encode('utf-8')
                link_buf.extend(encode_field(1, 2, encode_bytes(name_bytes)))

            # Hash (field 2, bytes)
            if link.cid is not None:
                if isinstance(link.cid, str):
                    # Convert string CID to bytes
                    cid_bytes = link.cid.encode('utf-8')
                else:
                    cid_bytes = link.cid
                link_buf.extend(encode_field(2, 2, encode_bytes(cid_bytes)))

            # Tsize (field 3, varint)
            if link.tsize is not None:
                link_buf.extend(encode_field(3, 0, encode_varint(link.tsize)))

            # Add the link as a nested message
            buf.extend(encode_field(1, 2, encode_bytes(bytes(link_buf))))

        # Encode data (field 2, bytes)
        if node.data is not None:
            buf.extend(encode_field(2, 2, encode_bytes(node.data)))

        return bytes(buf)

    def decode(buf):
        """Decode a protobuf message to a PBNode."""
        if isinstance(buf, bytes):
            buf = memoryview(buf)

        links = []
        data = None

        pos = 0
        while pos < len(buf):
            tag, pos = decode_varint(buf, pos)
            field_num = tag >> 3
            wire_type = tag & 0x7

            if field_num == 1:  # Links
                if wire_type != 2:
                    raise ValueError(f"Expected wire type 2 for field 1, got {wire_type}")

                # Read the nested message
                len_bytes, pos = decode_varint(buf, pos)
                link_buf = buf[pos:pos+len_bytes]
                pos += len_bytes

                # Parse the link
                link_pos = 0
                link_name = None
                link_hash = None
                link_tsize = None

                while link_pos < len(link_buf):
                    link_tag, link_pos = decode_varint(link_buf, link_pos)
                    link_field = link_tag >> 3
                    link_type = link_tag & 0x7

                    if link_field == 1:  # Name
                        if link_type != 2:
                            raise ValueError(f"Expected wire type 2 for link field 1, got {link_type}")

                        name_len, link_pos = decode_varint(link_buf, link_pos)
                        link_name = link_buf[link_pos:link_pos+name_len].tobytes().decode('utf-8')
                        link_pos += name_len

                    elif link_field == 2:  # Hash
                        if link_type != 2:
                            raise ValueError(f"Expected wire type 2 for link field 2, got {link_type}")

                        hash_len, link_pos = decode_varint(link_buf, link_pos)
                        link_hash = link_buf[link_pos:link_pos+hash_len].tobytes()
                        link_pos += hash_len

                    elif link_field == 3:  # Tsize
                        if link_type != 0:
                            raise ValueError(f"Expected wire type 0 for link field 3, got {link_type}")

                        link_tsize, link_pos = decode_varint(link_buf, link_pos)

                    else:
                        # Skip unknown field
                        if link_type == 0:  # Varint
                            _, link_pos = decode_varint(link_buf, link_pos)
                        elif link_type == 1:  # 64-bit
                            link_pos += 8
                        elif link_type == 2:  # Length-delimited
                            len_val, link_pos = decode_varint(link_buf, link_pos)
                            link_pos += len_val
                        else:
                            raise ValueError(f"Unknown wire type {link_type}")

                links.append(PBLink(name=link_name, cid=link_hash, tsize=link_tsize))

            elif field_num == 2:  # Data
                if wire_type != 2:
                    raise ValueError(f"Expected wire type 2 for field 2, got {wire_type}")

                len_bytes, pos = decode_varint(buf, pos)
                data = buf[pos:pos+len_bytes].tobytes()
                pos += len_bytes

            else:
                # Skip unknown field
                if wire_type == 0:  # Varint
                    _, pos = decode_varint(buf, pos)
                elif wire_type == 1:  # 64-bit
                    pos += 8
                elif wire_type == 2:  # Length-delimited
                    len_val, pos = decode_varint(buf, pos)
                    pos += len_val
                else:
                    raise ValueError(f"Unknown wire type {wire_type}")

        return PBNode(data=data, links=links)


def create_dag_node(data: bytes, links: List[Dict]) -> bytes:
    """
    Create a DAG-PB node with the given data and links.

    Args:
        data (bytes): The data to store in the node
        links (List[Dict]): Links to other nodes, each a dict with at least
            a "cid" key and optionally "name" and "tsize" keys.

    Returns:
        bytes: The encoded DAG-PB node
    """
    # Convert the links to PBLink objects
    pb_links = []
    for link in links:
        name = link.get("name")
        cid = link["cid"]  # This is required
        tsize = link.get("tsize")

        pb_links.append(PBLink(name=name, cid=cid, tsize=tsize))

    # Create and encode the node
    node = PBNode(data=data, links=pb_links)
    return encode(node)


def parse_dag_node(node_data: bytes) -> Tuple[bytes, List[Dict]]:
    """
    Parse a DAG-PB node into data and links.

    Args:
        node_data (bytes): The encoded DAG-PB node

    Returns:
        Tuple[bytes, List[Dict]]: The data and links from the node
    """
    node = decode(node_data)

    # Convert PBLink objects to dicts
    links = []
    for link in node.links:
        link_dict = {}
        if link.name is not None:
            link_dict["name"] = link.name
        if link.cid is not None:
            link_dict["cid"] = link.cid
        if link.tsize is not None:
            link_dict["tsize"] = link.tsize
        links.append(link_dict)

    return node.data, links
