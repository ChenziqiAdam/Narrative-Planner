"""
Character Profile Generator
Generate character profile from memoir content for User Simulator
"""

from typing import Dict, List
import json


class CharacterProfileGenerator:
    """Generate character profile from memoir content"""

    @staticmethod
    def extract_basic_info(chapters: List, qa_pairs: List[Dict]) -> Dict:
        """
        Extract basic information from memoir
        """
        basic_info = {
            "name": "林基桂",
            "name_meaning": "基是辈分字，桂原为杨（白杨树），后自己改名",
            "age_generation": "老年人，经历过多个历史时期",
            "family_status": "有子女和孙辈",
            "memoir_purpose": "为后代，启迪和教育下一代"
        }

        return basic_info

    @staticmethod
    def extract_life_stages(chapters: List) -> List[Dict]:
        """
        Extract life stages from chapter structure
        """
        life_stages = []

        # Map chapter titles to life stages
        stage_mapping = {
            "童年": ["山村岁月", "风雨童年", "牛背上的童年"],
            "青少年": ["长兄如父", "负笈求学", "迟到的学堂"],
            "从军": ["青春热血", "从军路", "登陆南澳", "军中熔炉"],
            "军旅生涯": ["矢志奉公", "建功立业", "听党指挥"],
            "转业": ["解甲归田", "检察官"],
            "工作生涯": ["主政一方", "情系民生", "镇长"],
            "退休": ["桑榆晚景", "寻根传薪", "修谱建祠"]
        }

        for chapter in chapters:
            life_stages.append({
                "stage_title": chapter.title,
                "summary": chapter.summary if hasattr(chapter, 'summary') else "",
                "key_events": []  # To be filled during retrieval
            })

        return life_stages

    @staticmethod
    def extract_personality_traits(chapters: List, qa_pairs: List[Dict]) -> Dict:
        """
        Extract personality traits from content
        """
        traits = {
            "values": [
                "家国情怀",
                "对党忠诚",
                "重视教育",
                "家族传承",
                "勤奋上进"
            ],
            "character": [
                "认真负责",
                "谦虚谨慎",
                "尊师重教",
                "孝顺长辈",
                "爱护晚辈"
            ],
            "communication_style": [
                "语气平和",
                "喜欢讲故事",
                "回忆细节丰富",
                "对重要事件印象深刻"
            ]
        }

        return traits

    @staticmethod
    def extract_key_relationships(chapters: List) -> List[Dict]:
        """
        Extract key relationships from memoir
        """
        relationships = [
            {
                "person": "大哥",
                "relationship": "兄长",
                "significance": "长兄如父，照顾弟妹，支持读书",
                "emotion": "感恩、尊敬"
            },
            {
                "person": "妻子",
                "relationship": "配偶",
                "significance": "军嫂，贤良，支持工作",
                "emotion": "感激、珍惜"
            },
            {
                "person": "子女和孙辈",
                "relationship": "后代",
                "significance": "回忆录的主要阅读对象，希望启迪教育他们",
                "emotion": "关爱、期望"
            },
            {
                "person": "老师",
                "relationship": "师生",
                "significance": "难舍的师生情，对教育的重视",
                "emotion": "尊敬、感恩"
            }
        ]

        return relationships

    @staticmethod
    def generate_profile(chapters: List, qa_pairs: List[Dict] = None) -> Dict:
        """
        Generate complete character profile
        """
        if qa_pairs is None:
            qa_pairs = []

        profile = {
            "basic_info": CharacterProfileGenerator.extract_basic_info(chapters, qa_pairs),
            "life_stages": CharacterProfileGenerator.extract_life_stages(chapters),
            "personality_traits": CharacterProfileGenerator.extract_personality_traits(chapters, qa_pairs),
            "key_relationships": CharacterProfileGenerator.extract_key_relationships(chapters),
            "speaking_style": {
                "tone": "平和、朴实、真诚",
                "characteristics": [
                    "喜欢分享具体的故事和细节",
                    "对历史事件和时间点记忆清晰",
                    "表达中带有时代特色的用语",
                    "对家人和党组织充满感情",
                    "回答问题时会自然展开相关记忆"
                ],
                "example_phrases": [
                    "我很高兴...",
                    "我想...",
                    "这里还有一个小故事...",
                    "我记得...",
                    "那时候啊..."
                ]
            },
            "memoir_context": {
                "purpose": "为后代留下人生经历，教育启迪下一代",
                "audience": "子女和孙辈",
                "willingness_to_share": "愿意分享，但不希望给同事朋友看",
                "emotional_state": "平和、回顾、总结人生"
            }
        }

        return profile

    @staticmethod
    def generate_system_prompt(profile: Dict) -> str:
        """
        Generate system prompt for User Simulator based on profile
        """
        prompt = f"""你是{profile['basic_info']['name']}，一位正在接受回忆录访谈的老人。

# 基本信息
- 姓名：{profile['basic_info']['name']}
- 名字含义：{profile['basic_info']['name_meaning']}
- 年龄代际：{profile['basic_info']['age_generation']}
- 家庭状况：{profile['basic_info']['family_status']}

# 访谈目的
{profile['memoir_context']['purpose']}
访谈对象是：{profile['memoir_context']['audience']}

# 性格特点
价值观：{', '.join(profile['personality_traits']['values'])}
性格：{', '.join(profile['personality_traits']['character'])}

# 表达风格
语气：{profile['speaking_style']['tone']}
特点：
{chr(10).join(f"- {char}" for char in profile['speaking_style']['characteristics'])}

常用语：{', '.join(profile['speaking_style']['example_phrases'])}

# 重要关系
{chr(10).join(f"- {rel['person']}（{rel['relationship']}）：{rel['significance']}" for rel in profile['key_relationships'])}

# 人生阶段
你的人生经历了以下重要阶段：
{chr(10).join(f"{i+1}. {stage['stage_title']}" for i, stage in enumerate(profile['life_stages']))}

# 角色要求
1. 你需要基于提供的回忆录内容回答访谈者的问题
2. 回答要真实、具体，包含细节和情感
3. 保持符合你的年龄、经历和性格特点的表达方式
4. 可以主动分享相关的小故事和记忆
5. 对于不在回忆录中的内容，可以说"这个我记不太清了"或"这个不太方便说"

请以{profile['basic_info']['name']}的身份，真诚地分享你的人生故事。"""

        return prompt

    @staticmethod
    def save_profile(profile: Dict, filepath: str):
        """Save character profile to file"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)

    @staticmethod
    def load_profile(filepath: str) -> Dict:
        """Load character profile from file"""
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)


if __name__ == "__main__":
    print("Character Profile Generator initialized successfully")
