Feature: LibP2P Networking
  Peer-to-peer networking using LibP2P protocol

  Scenario: Initialize LibP2P node
    Given node configuration parameters
    When the LibP2P node is initialized
    Then the node is ready for networking

  Scenario: Listen on network address
    Given a multiaddress to listen on
    When the node starts listening
    Then the node accepts incoming connections

  Scenario: Dial peer connection
    Given a peer multiaddress
    When connection is initiated
    Then a connection to the peer is established

  Scenario: Handle incoming connection
    Given the node is listening
    When a peer connects
    Then the connection is accepted

  Scenario: Send message to peer
    Given an active peer connection
    And a message to send
    When the message is sent
    Then the peer receives the message

  Scenario: Receive message from peer
    Given an active peer connection
    When a peer sends a message
    Then the message is received

  Scenario: Discover peers on network
    Given peer discovery is enabled
    When discovery runs
    Then available peers are found

  Scenario: Advertise service on network
    Given a service to advertise
    When advertising starts
    Then peers can discover the service

  Scenario: Handle connection close
    Given an active peer connection
    When the connection is closed
    Then resources are cleaned up

  Scenario: Generate peer identity
    Given key pair parameters
    When peer identity generation is requested
    Then a unique peer ID is created
