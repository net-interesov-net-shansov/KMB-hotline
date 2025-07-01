import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch
from bot import Appeal, is_valid_media_format, format_file_size, send_email, send_to_operator


class TestUtilityFunctions:
    """Тесты утилитарных функций"""
    
    def test_is_valid_media_format(self):
        """Тест проверки форматов файлов"""
        # Допустимые форматы
        assert is_valid_media_format("photo.jpg") == True
        assert is_valid_media_format("document.jpeg") == True
        assert is_valid_media_format("image.png") == True
        assert is_valid_media_format("file.pdf") == True
        assert is_valid_media_format("FILE.PDF") == True  # Регистр
        
        # Недопустимые форматы
        assert is_valid_media_format("video.mp4") == False
        assert is_valid_media_format("audio.mp3") == False
        assert is_valid_media_format("document.doc") == False
        assert is_valid_media_format("archive.zip") == False
        assert is_valid_media_format("no_extension") == False
    
    def test_format_file_size(self):
        """Тест форматирования размера файлов"""
        assert format_file_size(500) == "500 B"
        assert format_file_size(1024) == "1.0 KB"
        assert format_file_size(1536) == "1.5 KB"
        assert format_file_size(1024 * 1024) == "1.0 MB"
        assert format_file_size(1024 * 1024 * 2.5) == "2.5 MB"


class TestAppealDataClass:
    """Тесты класса Appeal"""
    
    def test_appeal_creation(self):
        """Тест создания объекта Appeal"""
        appeal = Appeal(
            instance="Директор",
            topic="Тестовое обращение",
            text="Текст обращения",
            full_name="Иванов Иван Иванович",
            contact_method="Telegram"
        )
        
        assert appeal.instance == "Директор"
        assert appeal.topic == "Тестовое обращение" 
        assert appeal.text == "Текст обращения"
        assert appeal.full_name == "Иванов Иван Иванович"
        assert appeal.contact_method == "Telegram"
        assert appeal.media_files == []
        assert appeal.created_at is not None
    
    def test_appeal_with_media(self):
        """Тест создания обращения с медиа-файлами"""
        media_files = [
            {'type': 'photo', 'file_id': 'test123', 'file_name': 'photo.jpg', 'file_size': 1024}
        ]
        
        appeal = Appeal(
            instance="Психолог",
            topic="Обращение с фото",
            text="Прикладываю фотографию",
            full_name="Петров Петр Петрович",
            contact_method="Email: petrov@example.com",
            media_files=media_files
        )
        
        assert len(appeal.media_files) == 1
        assert appeal.media_files[0]['file_name'] == 'photo.jpg'


class TestEmailIntegration:
    """Тесты почтовой интеграции"""
    
    @pytest.mark.asyncio
    @patch('bot.smtplib.SMTP')
    @patch('bot.bot')
    async def test_send_email_success(self, mock_bot, mock_smtp):
        """Тест успешной отправки email"""
        # Настройка мока
        mock_server = Mock()
        mock_smtp.return_value = mock_server
        mock_bot.get_file = AsyncMock()
        mock_bot.download_file = AsyncMock()
        
        # Создание тестового обращения
        appeal = Appeal(
            instance="Директор",
            topic="Тест email",
            text="Тестовое сообщение",
            full_name="Тестов Тест Тестович",
            contact_method="test@example.com"
        )
        
        # Тест отправки
        with patch('bot.SMTP_USER', 'sender@test.com'), \
             patch('bot.SMTP_PASSWORD', 'password'), \
             patch('bot.CORPORATE_EMAIL', 'corp@test.com'), \
             patch('bot.SMTP_SERVER', 'smtp.test.com'), \
             patch('bot.SMTP_PORT', 587):
            
            result = await send_email(appeal)
            
            # Проверки
            assert result == True
            mock_smtp.assert_called_once_with('smtp.test.com', 587)
            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with('sender@test.com', 'password')
            mock_server.sendmail.assert_called_once()
            mock_server.quit.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('bot.smtplib.SMTP')
    async def test_send_email_failure(self, mock_smtp):
        """Тест неудачной отправки email"""
        # Настройка мока для генерации исключения
        mock_smtp.side_effect = Exception("SMTP Error")
        
        appeal = Appeal(
            instance="Директор",
            topic="Тест ошибки",
            text="Тестовое сообщение",
            full_name="Тестов Тест Тестович",
            contact_method="test@example.com"
        )
        
        result = await send_email(appeal)
        assert result == False


class TestTelegramIntegration:
    """Тесты Telegram интеграции"""
    
    @pytest.mark.asyncio
    @patch('bot.bot')
    async def test_send_to_operator_success(self, mock_bot):
        """Тест успешной отправки оператору"""
        # Настройка мока
        mock_bot.send_message = AsyncMock()
        mock_message = Mock()
        mock_message.message_id = 123
        mock_bot.send_message.return_value = mock_message
        
        # Создание тестового обращения
        appeal = Appeal(
            instance="Заведующий отделением",
            topic="Тест Telegram",
            text="Тестовое обращение для оператора",
            full_name="Студентов Студент Студентович",
            contact_method="Telegram"
        )
        
        with patch('bot.OPERATOR_ID', 123456789):
            result = await send_to_operator(appeal)
            
            # Проверки
            assert result == True
            mock_bot.send_message.assert_called_once()
            call_args = mock_bot.send_message.call_args
            assert call_args[1]['chat_id'] == 123456789
            assert "НОВОЕ ОБРАЩЕНИЕ" in call_args[1]['text']
            assert appeal.topic in call_args[1]['text']
    
    @pytest.mark.asyncio
    @patch('bot.bot')
    async def test_send_to_operator_with_media(self, mock_bot):
        """Тест отправки оператору с медиа-файлами"""
        # Настройка моков
        mock_bot.send_message = AsyncMock()
        mock_bot.send_photo = AsyncMock()
        mock_bot.send_media_group = AsyncMock()
        
        # Обращение с одним фото
        appeal_single = Appeal(
            instance="Психолог",
            topic="Обращение с фото",
            text="Прикладываю одну фотографию",
            full_name="Фотографов Фото Фотович",
            contact_method="Telegram",
            media_files=[
                {'type': 'photo', 'file_id': 'photo123', 'file_name': 'image.jpg', 'file_size': 2048}
            ]
        )
        
        with patch('bot.OPERATOR_ID', 123456789):
            result = await send_to_operator(appeal_single)
            
            assert result == True
            mock_bot.send_message.assert_called_once()
            mock_bot.send_photo.assert_called_once()
            
        # Сброс моков
        mock_bot.reset_mock()
        
        # Обращение с несколькими файлами
        appeal_multiple = Appeal(
            instance="Директор", 
            topic="Обращение с файлами",
            text="Прикладываю несколько файлов",
            full_name="Файлов Файл Файлович",
            contact_method="Email",
            media_files=[
                {'type': 'photo', 'file_id': 'photo1', 'file_name': 'img1.jpg', 'file_size': 1024},
                {'type': 'document', 'file_id': 'doc1', 'file_name': 'doc.pdf', 'file_size': 3072}
            ]
        )
        
        with patch('bot.OPERATOR_ID', 123456789):
            result = await send_to_operator(appeal_multiple)
            
            assert result == True
            mock_bot.send_message.assert_called_once()
            mock_bot.send_media_group.assert_called_once()


class TestValidation:
    """Тесты валидации данных"""
    
    def test_topic_length_validation(self):
        """Тест валидации длины темы"""
        # Нормальная тема
        normal_topic = "Обычная тема обращения"
        assert len(normal_topic) <= 100
        
        # Слишком длинная тема
        long_topic = "А" * 101
        assert len(long_topic) > 100
    
    def test_text_length_validation(self):
        """Тест валидации длины текста"""
        # Нормальный текст
        normal_text = "Обычный текст обращения с подробным описанием проблемы."
        assert len(normal_text) <= 4000
        
        # Слишком длинный текст  
        long_text = "А" * 4001
        assert len(long_text) > 4000
    
    def test_fullname_validation(self):
        """Тест валидации ФИО"""
        # Корректные ФИО
        valid_names = [
            "Иванов Иван Иванович",
            "Петрова Анна Сергеевна", 
            "Сидоров Алексей Владимирович"
        ]
        
        for name in valid_names:
            assert len(name.strip()) >= 5
        
        # Некорректные ФИО
        invalid_names = ["", "   ", "Ив", "А Б"]
        
        for name in invalid_names:
            assert len(name.strip()) < 5


# Запуск тестов
if __name__ == "__main__":
    # Запуск всех тестов
    pytest.main([__file__, "-v"])
    
    # Или запуск конкретного теста:
    # pytest.main([__file__ + "::TestUtilityFunctions::test_is_valid_media_format", "-v"])