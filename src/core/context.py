from core.model import get_model


class Context:
    def __init__(self):
        self.llm, self.provider_name, self.model_info = get_model()
        self.context_length = self.model_info.context_length
        self.max_tokens = self.model_info.max_tokens
        self.support_data_types = self.model_info.support_data_types
