from .types import ClientConfig, ClientStates, Settings
from .protocol import Request
from .transports import start_tcp_transport
from .rpc import Client, attach_stdio_client
from .process import start_server
from .url import filename_to_uri
from .logging import debug
import os
from .protocol import completion_item_kinds, symbol_kinds
try:
    from typing import Callable, Dict, Any, Optional, List, Union
    assert Callable and Dict and Any and Optional and List and Union
except ImportError:
    pass


def create_session(config: ClientConfig, project_path: str, env: dict, settings: Settings,
                   on_created=None, on_ended: 'Optional[Callable[[str], None]]' = None,
                   bootstrap_client=None) -> 'Optional[Session]':
    session = None
    if config.binary_args:

        process = start_server(config.binary_args, project_path, env, settings.log_stderr)
        if process:
            if config.tcp_port:
                transport = start_tcp_transport(config.tcp_port, config.tcp_host)
                if transport:
                    session = Session(config, project_path, Client(transport, settings), on_created, on_ended)
                else:
                    # try to terminate the process
                    try:
                        process.terminate()
                    except Exception:
                        pass
            else:
                client = attach_stdio_client(process, settings)
                session = Session(config, project_path, client, on_created, on_ended)
    else:
        if config.tcp_port:
            transport = start_tcp_transport(config.tcp_port)

            session = Session(config, project_path, Client(transport, settings),
                              on_created, on_ended)
        elif bootstrap_client:
            session = Session(config, project_path, bootstrap_client,
                              on_created, on_ended)
        else:
            debug("No way to start session")

    return session


def basic_capability() -> 'Dict[str, Any]':
    return {"dynamicRegistration": False}


def supported_content_formats() -> 'List[str]':
    return ["markdown", "plaintext"]


def value_set(items: 'List[int]') -> 'Dict[str, List[int]]':
    return {"valueSet": items}


def symbol_kind_value_set() -> 'Dict[str, List[int]]':
    return value_set(symbol_kinds)


def code_action_kind_value_set() -> 'Dict[str, List[int]]':
    return value_set([])


def completion_item_kind_value_set() -> 'Dict[str, List[int]]':
    return value_set(completion_item_kinds)


def synchronization() -> 'Dict[str, Any]':
    result = basic_capability()
    result["willSave"] = False
    result["willSaveWaitUntil"] = False
    result["didSave"] = True
    return result


def hover() -> 'Dict[str, Any]':
    result = basic_capability()
    result["contentFormat"] = supported_content_formats()
    return result


def completion() -> 'Dict[str, Any]':
    result = basic_capability()
    result["completionItem"] = {
        "snippetSupport": True,
        "commitCharacterSupport": False,
        "documentationFormat": supported_content_formats(),
        "deprecatedSupport": False,
        "preselectSupport": False
    }
    result["completionItemKind"] = completion_item_kind_value_set()
    return result


def signature_help() -> 'Dict[str, Any]':
    result = basic_capability()
    result["signatureInformation"] = {
        "documentationFormat": supported_content_formats(),
        "parameterInformation": {"labelOffsetSupport": True}
    }
    return result


def document_symbol() -> 'Dict[str, Any]':
    result = basic_capability()
    result["symbolKind"] = symbol_kind_value_set()
    return result


def code_action() -> 'Dict[str, Any]':
    result = basic_capability()
    result["codeActionLiteralSupport"] = {
        "codeActionKind": code_action_kind_value_set()
    }
    return result


def goto_symbol() -> 'Dict[str, Any]':
    result = basic_capability()
    result["linkSupport"] = False
    return result


def rename() -> 'Dict[str, Any]':
    result = basic_capability()
    result["prepareSupport"] = False
    return result


def publish_diagnostics() -> 'Dict[str, Any]':
    return {"relatedInformation": False}


def text_document_capabilities() -> 'Dict[str, dict]':
    return {
        "synchronization": synchronization(),
        "completion": completion(),
        "hover": hover(),
        "signatureHelp": signature_help(),
        "references": basic_capability(),
        "documentHighlight": basic_capability(),
        "documentSymbol": document_symbol(),
        "formatting": basic_capability(),
        "rangeFormatting": basic_capability(),
        # missing: onTypeFormatting
        "declaration": goto_symbol(),
        "definition": goto_symbol(),
        "typeDefinition": goto_symbol(),
        "implementation": goto_symbol(),
        "codeAction": code_action(),
        # missing: codeLens
        # missing: documentLink
        # missing: colorProvider
        "rename": rename(),
        "publishDiagnostics": publish_diagnostics(),
        # missing: foldingRange
    }


def workspace_symbol() -> 'Dict[str, Any]':
    result = basic_capability()
    result["symbolKind"] = symbol_kind_value_set()
    return result


def workspace_capabilities() -> 'Dict[str, Union[bool, dict]]':
    return {
        "applyEdit": True,
        # missing: workspaceEdit
        "didChangeConfiguration": basic_capability(),
        # missing: didChangeWatchedFiles
        "symbol": workspace_symbol(),
        "executeCommand": basic_capability(),
        # missing: workspaceFolders
        # missing: configuration
    }


def capabilities() -> 'Dict[str, dict]':
    return {
        "textDocument": text_document_capabilities(),
        "workspace": workspace_capabilities()
    }


def get_initialize_params(project_path: str, config: ClientConfig):
    initializeParams = {
        "processId": os.getpid(),
        "rootUri": filename_to_uri(project_path),
        "rootPath": project_path,
        "capabilities": capabilities(),
        # missing: trace
        # missing: workspaceFolders
    }
    if config.init_options:
        initializeParams['initializationOptions'] = config.init_options

    return initializeParams


class Session(object):
    def __init__(self, config: ClientConfig, project_path, client: Client,
                 on_created=None, on_ended: 'Optional[Callable[[str], None]]' = None) -> None:
        self.config = config
        self.project_path = project_path
        self.state = ClientStates.STARTING
        self._on_created = on_created
        self._on_ended = on_ended
        self.capabilities = dict()  # type: Dict[str, Any]
        self.client = client
        self.initialize()

    def has_capability(self, capability):
        return capability in self.capabilities and self.capabilities[capability] is not False

    def get_capability(self, capability):
        return self.capabilities.get(capability)

    def initialize(self):
        params = get_initialize_params(self.project_path, self.config)
        self.client.send_request(
            Request.initialize(params),
            lambda result: self._handle_initialize_result(result))

    def _handle_initialize_result(self, result):
        self.state = ClientStates.READY
        self.capabilities = result.get('capabilities', dict())
        if self._on_created:
            self._on_created(self)

    def end(self):
        self.state = ClientStates.STOPPING
        self.client.send_request(
            Request.shutdown(),
            lambda result: self._handle_shutdown_result(),
            lambda: self._handle_shutdown_result())

    def _handle_shutdown_result(self):
        self.client.exit()
        self.client = None
        self.capabilities = dict()
        if self._on_ended:
            self._on_ended(self.config.name)
