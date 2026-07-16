import logging

class DynamicExtraFormatter(logging.Formatter):
    """Custom formatter that automatically extracts and appends any 

    extra={'key': 'value'} arguments passed to log methods.
    """
    # 💡 Comprehensive list of Python's internal LogRecord attributes to protect them
    STANDARD_ATTRS = {
        'args', 'asctime', 'exc_info', 'exc_text', 'created', 'taskName', 'filename',
        'funcName', 'levelname', 'levelno', 'lineno', 'module', 'msecs', 'name',
        'message', 'msg', 'pathname', 'process', 'processName',
        'relativeCreated', 'stack_info', 'thread', 'threadName'
    }

    def format(self, record: logging.LogRecord) -> str:
        standard_msg = super().format(record)
        
        extra_fields = {
            k: v for k, v in record.__dict__.items() 
            if k not in self.STANDARD_ATTRS
        }
        
        if extra_fields:
            # 💡 Directly print the dictionary structure as a text string
            return f"{standard_msg} | extra: {extra_fields}"
            
        return standard_msg


def setup_logging(level: str = "INFO") -> None:
    fmt = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    # logging.basicConfig(level=level, format=fmt)

    # Get the root logger setup
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Route output through our custom formatter
    handler = logging.StreamHandler()
    handler.setFormatter(DynamicExtraFormatter(fmt))
    
    # Clear default handlers to avoid duplicate log prints in FastAPI/Uvicorn
    root_logger.handlers = []
    root_logger.addHandler(handler)

    # Reduce verbosity for some noisy libraries
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


logger = logging.getLogger("prlens")
