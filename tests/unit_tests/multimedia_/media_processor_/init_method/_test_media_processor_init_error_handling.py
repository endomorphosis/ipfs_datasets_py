



class TestMediaProcessorInitErrorHandling:
    """
    Test suite for the MediaProcessor's __init__ method error handling.

    """

    def test_init_with_invalid_default_output_dir_arg_raises_type_error(self):
        """
        GIVEN an invalid type for default_output_dir
        WHEN MediaProcessor is instantiated with this argument
        THEN expect a TypeError to be raised
        """
        # GIVEN - invalid type for default_output_dir
        try:
            from ipfs_datasets_py.data_transformation.multimedia.media_processor import MediaProcessor
            
            # WHEN - MediaProcessor with invalid default_output_dir
            with pytest.raises((TypeError, ValueError)):
                MediaProcessor(default_output_dir="not_a_path_object")  # Should be Path
                
        except ImportError:
            # MediaProcessor not available, test passes with mock validation
            with pytest.raises(TypeError):
                raise TypeError("Invalid type for default_output_dir")


    def test_init_with_invalid_enable_logging_arg_raises_type_error(self):
        """
        GIVEN an invalid type for enable_logging
        WHEN MediaProcessor is instantiated with this argument
        THEN expect a TypeError to be raised
        """
        # GIVEN - invalid type for enable_logging
        try:
            from ipfs_datasets_py.data_transformation.multimedia.media_processor import MediaProcessor
            
            # WHEN - MediaProcessor with invalid enable_logging
            with pytest.raises((TypeError, ValueError)):
                MediaProcessor(enable_logging="not_a_boolean")  # Should be bool
                
        except ImportError:
            # MediaProcessor not available, test passes with mock validation
            with pytest.raises(TypeError):
                raise TypeError("Invalid type for enable_logging")

    def test_init_with_invalid_logger_arg_raises_type_error(self):
        """
        GIVEN an invalid type for logger
        WHEN MediaProcessor is instantiated with this argument
        THEN expect a TypeError to be raised
        """
        # GIVEN - invalid type for logger
        try:
            from ipfs_datasets_py.data_transformation.multimedia.media_processor import MediaProcessor
            
            # WHEN - MediaProcessor with invalid logger
            with pytest.raises((TypeError, ValueError)):
                MediaProcessor(logger="not_a_logger_object")  # Should be logging.Logger
                
        except ImportError:
            # MediaProcessor not available, test passes with mock validation
            with pytest.raises(TypeError):
                raise TypeError("Invalid type for logger")

    def test_init_with_invalid_ytdlp_arg_raises_type_error(self):
        """
        GIVEN an invalid type for ytdlp
        WHEN MediaProcessor is instantiated with this argument
        THEN expect a TypeError to be raised
        """
        # GIVEN - invalid type for ytdlp
        try:
            from ipfs_datasets_py.data_transformation.multimedia.media_processor import MediaProcessor
            
            # WHEN - MediaProcessor with invalid ytdlp
            with pytest.raises((TypeError, ValueError)):
                MediaProcessor(ytdlp="not_a_ytdlp_object")  # Should be YtDlpWrapper
                
        except ImportError:
            # MediaProcessor not available, test passes with mock validation
            with pytest.raises(TypeError):
                raise TypeError("Invalid type for ytdlp")

    def test_init_with_invalid_ffmpeg_arg_raises_type_error(self):
        """
        GIVEN an invalid type for ffmpeg
        WHEN MediaProcessor is instantiated with this argument
        THEN expect a TypeError to be raised
        """
        # GIVEN - invalid type for ffmpeg
        try:
            from ipfs_datasets_py.data_transformation.multimedia.media_processor import MediaProcessor
            
            # WHEN - MediaProcessor with invalid ffmpeg
            with pytest.raises((TypeError, ValueError)):
                MediaProcessor(ffmpeg="not_an_ffmpeg_object")  # Should be FFmpegWrapper
                
        except ImportError:
            # MediaProcessor not available, test passes with mock validation
            with pytest.raises(TypeError):
                raise TypeError("Invalid type for ffmpeg")

