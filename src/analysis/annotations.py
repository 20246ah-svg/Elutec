from datetime import datetime

class Annotation:
    """Класс для хранения данных о метке на графике."""
    def __init__(self, time_ms, description="", color=None, is_auto=False,
                 r=None, g=None, b=None,
                 rgb_sum_slope_30s=None, transition_score=None):
        self.time_ms = time_ms
        self.description = description
        self.color = color or "#FF4444"
        self.created_at = datetime.now()
        self.is_auto = bool(is_auto)
        self.r = self._to_optional_float(r)
        self.g = self._to_optional_float(g)
        self.b = self._to_optional_float(b)
        self.rgb_sum_slope_30s = self._to_optional_float(rgb_sum_slope_30s)
        self.transition_score = self._to_optional_float(transition_score)

    @staticmethod
    def _to_optional_float(value):
        if value is None:
            return None
        try:
            return float(value)
        except Exception:
            return None

    def to_dict(self):
        return {
            'time_ms': self.time_ms,
            'description': self.description,
            'color': self.color,
            'created_at': self.created_at.isoformat(),
            'is_auto': self.is_auto,
            'r': self.r,
            'g': self.g,
            'b': self.b,
            'rgb_sum_slope_30s': self.rgb_sum_slope_30s,
            'transition_score': self.transition_score,
        }
    
    @classmethod
    def from_dict(cls, data):
        ann = cls(
            data.get('time_ms'),
            data.get('description', ''),
            data.get('color'),
            is_auto=data.get('is_auto', False),
            r=data.get('r'),
            g=data.get('g'),
            b=data.get('b'),
            rgb_sum_slope_30s=data.get('rgb_sum_slope_30s'),
            transition_score=data.get('transition_score'),
        )
        created_at = data.get('created_at')
        if created_at:
            try:
                ann.created_at = datetime.fromisoformat(created_at)
            except Exception:
                pass
        return ann


class AnnotationManager:
    """Управляет метками на графике."""
    COLORS = [
        "#FF4444",           
        "#44FF44",           
        "#4444FF",         
        "#FFFF44",          
        "#FF44FF",              
        "#44FFFF",           
        "#FF8844",             
        "#88FF44",             
        "#FF4488",           
        "#4488FF",                
    ]
    
    def __init__(self):
        self.annotations = []
        self._color_index = 0
    
    def add_annotation(self, time_ms, description="", color=None, is_auto=False,
                       r=None, g=None, b=None,
                       rgb_sum_slope_30s=None, transition_score=None):
        if color is None:
            color = self.COLORS[self._color_index % len(self.COLORS)]
            self._color_index += 1
        ann = Annotation(
            time_ms,
            description,
            color,
            is_auto=is_auto,
            r=r,
            g=g,
            b=b,
            rgb_sum_slope_30s=rgb_sum_slope_30s,
            transition_score=transition_score,
        )
        self.annotations.append(ann)
        self.annotations.sort(key=lambda a: a.time_ms)
        return ann
    
    def remove_annotation(self, index):
        if 0 <= index < len(self.annotations):
            del self.annotations[index]
    
    def get_annotations(self):
        return self.annotations
    
    def clear(self):
        self.annotations = []
        self._color_index = 0
    
    

