#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>

#include "../native/Client.hpp"
#include "PsuNoise.hpp"

#include <array>
#include <atomic>
#include <cmath>

namespace {

juce::File runtimePath() {
    static const int anchor=0;
    HMODULE module=nullptr;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                           GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           reinterpret_cast<LPCWSTR>(&anchor),&module))
        return {};
    std::array<wchar_t,32768> path{};
    const auto size=GetModuleFileNameW(module,path.data(),static_cast<DWORD>(path.size()));
    if (!size || size>=path.size()) return {};
    return juce::File(juce::String(path.data())).getParentDirectory().getParentDirectory()
        .getChildFile("Resources").getChildFile("163x-native.dll");
}

class Compressor final : public juce::AudioProcessor {
public:
    Compressor()
        : AudioProcessor(BusesProperties().withInput("Input",juce::AudioChannelSet::stereo(),true)
                                           .withOutput("Output",juce::AudioChannelSet::stereo(),true)),
          state(*this,nullptr,"Settings",parameters()) {
        const auto path=runtimePath().getFullPathName();
        if (engine.open(path.toWideCharPointer())) setLatencySamples(engine.latency());
    }

    const juce::String getName() const override {return "163X";}
    bool acceptsMidi() const override {return false;}
    bool producesMidi() const override {return false;}
    bool isMidiEffect() const override {return false;}
    double getTailLengthSeconds() const override {return 0.5;}
    int getNumPrograms() override {return 1;}
    int getCurrentProgram() override {return 0;}
    void setCurrentProgram(int) override {}
    const juce::String getProgramName(int) override {return {};}
    void changeProgramName(int,const juce::String&) override {}
    bool hasEditor() const override {return true;}
    juce::AudioProcessorEditor* createEditor() override;

    bool isBusesLayoutSupported(const BusesLayout& layout) const override {
        const auto in=layout.getMainInputChannelSet();
        return in==layout.getMainOutputChannelSet() &&
               (in==juce::AudioChannelSet::mono() || in==juce::AudioChannelSet::stereo());
    }
    void prepareToPlay(double sampleRate,int blockSize) override {
        ready=engine.prepare(sampleRate,getTotalNumInputChannels(),blockSize);
        if (ready) setLatencySamples(engine.latency());
        failed.store(!ready);
        gainReduction.store(0);
        psu.prepare(sampleRate);noiseSmooth=noise->load();noiseAlpha=float(1-std::exp(-1/(.01*sampleRate)));
    }
    void releaseResources() override {
        engine.stop();
        ready=false;
    }
    void processBlock(juce::AudioBuffer<float>& audio,juce::MidiBuffer&) override {
        process(audio,false);
    }
    void processBlockBypassed(juce::AudioBuffer<float>& audio,juce::MidiBuffer&) override {
        process(audio,true);
    }
    void getStateInformation(juce::MemoryBlock& data) override {
        copyXmlToBinary(*state.copyState().createXml(),data);
    }
    void setStateInformation(const void* data,int size) override {
        const auto xml=getXmlFromBinary(data,size);
        if (xml && xml->hasTagName(state.state.getType()))
            state.replaceState(juce::ValueTree::fromXml(*xml));
    }

    juce::AudioProcessorValueTreeState state;
    std::atomic<float> gainReduction{0};
    std::atomic<bool> failed{false};

private:
    static juce::AudioProcessorValueTreeState::ParameterLayout parameters() {
        juce::AudioProcessorValueTreeState::ParameterLayout layout;
        layout.add(std::make_unique<juce::AudioParameterFloat>(
            juce::ParameterID{"compression",1},"Compression",juce::NormalisableRange<float>{0,1,0.0001f},0.45f));
        layout.add(std::make_unique<juce::AudioParameterFloat>(
            juce::ParameterID{"level",1},"Level Set",juce::NormalisableRange<float>{-30,10,0.01f},-10.0f));
        layout.add(std::make_unique<juce::AudioParameterBool>(juce::ParameterID{"noise",1},"PSU Noise",false));
        for (const auto& id : {juce::String("inputTrim"),juce::String("outputTrim")})
            layout.add(std::make_unique<juce::AudioParameterFloat>(juce::ParameterID{id,1},id=="inputTrim"?"Digital Input":"Digital Output",juce::NormalisableRange<float>{-12,12,0.1f},0.0f));
        return layout;
    }

    void process(juce::AudioBuffer<float>& audio,bool dry) {
        if (!ready || audio.getNumSamples()==0) return;
        const mkii::native::Controls controls{more->load(),(level->load()+30)/40};
        const float inDb=inputTrim->load();
        if (!dry && inDb!=0.f) audio.applyGain(juce::Decibels::decibelsToGain(inDb));
        const bool complete=engine.process(audio.getArrayOfWritePointers(),audio.getNumSamples(),
                                           controls,isNonRealtime(),dry);
        const float outDb=outputTrim->load();
        if (!dry && outDb!=0.f) audio.applyGain(juce::Decibels::decibelsToGain(outDb));
        if(!dry) {
            const float target=noise->load();
            if(target!=0 || noiseSmooth!=0) for(int i=0;i<audio.getNumSamples();++i){
                noiseSmooth+=noiseAlpha*(target-noiseSmooth);
                if(std::abs(noiseSmooth-target)<1e-6f)noiseSmooth=target;
                for(int c=0;c<audio.getNumChannels();++c)audio.getWritePointer(c)[i]+=noiseSmooth*psu.next(c);
                psu.advance();
            }
        }
        failed.store(!complete || engine.failedSolves()!=0);
        gainReduction.store(engine.readMeters().gainReductionDb);
    }

    mkii::native::Client engine;
    const std::atomic<float>* more=state.getRawParameterValue("compression");
    const std::atomic<float>* level=state.getRawParameterValue("level");
    const std::atomic<float>* noise=state.getRawParameterValue("noise");
    const std::atomic<float>* inputTrim=state.getRawParameterValue("inputTrim");
    const std::atomic<float>* outputTrim=state.getRawParameterValue("outputTrim");
    mkii::PsuNoise psu;
    float noiseSmooth=0,noiseAlpha=.002f;
    bool ready=false;
};

class Panel final : public juce::AudioProcessorEditor, private juce::Timer {
public:
    explicit Panel(Compressor& owner)
        : AudioProcessorEditor(owner), processor(owner) {
        compression.setSliderStyle(juce::Slider::LinearHorizontal);
        compression.setTextBoxStyle(juce::Slider::NoTextBox,false,0,0);
        compression.setName("Compression");
        level.setSliderStyle(juce::Slider::RotaryHorizontalVerticalDrag);
        level.setTextBoxStyle(juce::Slider::NoTextBox,false,0,0);
        level.setName("Level Set");
        for (auto* control : {&compression,&level}) {
            control->setLookAndFeel(&face);
            control->setPopupDisplayEnabled(true,true,this);
            addAndMakeVisible(*control);
        }
        compressionAttachment=std::make_unique<Attachment>(processor.state,"compression",compression);
        levelAttachment=std::make_unique<Attachment>(processor.state,"level",level);
        noiseButton.setButtonText("PSU Noise");
        addAndMakeVisible(noiseButton);
        noiseAttachment=std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment>(processor.state,"noise",noiseButton);
        settings.setButtonText("Settings  v");
        addAndMakeVisible(settings);
        settings.onClick=[this]{
            juce::PopupMenu menu;
            menu.addCustomItem(1,std::make_unique<TrimItem>(processor.state,"inputTrim","Digital Input"),nullptr);
            menu.addCustomItem(2,std::make_unique<TrimItem>(processor.state,"outputTrim","Digital Output"),nullptr);
            menu.showMenuAsync(juce::PopupMenu::Options().withTargetComponent(&settings));
        };
        setSize(850,201);
        startTimerHz(30);
    }
    ~Panel() override {
        compression.setLookAndFeel(nullptr);
        level.setLookAndFeel(nullptr);
    }

    void resized() override {
        compression.setBounds(261,69,287,27);
        level.setBounds(630,56,60,57);
        noiseButton.setBounds(10,176,120,24);
        settings.setBounds(710,176,130,24);
    }
    void paint(juce::Graphics& g) override {
        const auto metal=juce::Colour(0xff242327);
        const auto letters=juce::Colour(0xffeeeae2);
        g.setGradientFill({metal.brighter(0.18f),0,0,metal.darker(0.38f),0,175,false});
        g.fillRect(0,0,850,175);
        g.setColour(juce::Colour(0xff101014));g.fillRect(0,175,850,26);
        g.setColour(juce::Colour(0xff0f0e10));
        g.drawRect(getLocalBounds());
        for (int y : {16,159}) for (int x : {18,832}) {
            g.setColour(juce::Colour(0xff101013));
            g.fillEllipse(float(x-8),float(y-8),16.0f,16.0f);
            g.setColour(juce::Colour(0xff3b393f));
            g.drawLine(float(x-4),float(y+2),float(x+4),float(y-2),1.4f);
        }
        const auto label=[&](juce::String text,int x,int y,int width,int height,float size) {
            g.setColour(letters);
            g.setFont(juce::Font(juce::FontOptions(size,juce::Font::bold)));
            g.drawText(text,x,y,width,height,juce::Justification::centred);
        };
        label("163X",23,101,102,31,29);
        label("STEREO",133,49,74,12,11);
        label("SLAVE",133,60,74,12,11);
        label("POWER",133,94,74,12,11);
        g.setColour(juce::Colour(0xff311316));
        g.fillEllipse(167,75,7,7);
        g.setColour(processor.failed.load()?juce::Colour(0xffffa244):juce::Colour(0xfff33b29));
        g.fillEllipse(167,111,7,7);
        g.setColour(juce::Colour(0xff141315));
        g.fillRect(239,36,340,20);
        constexpr std::array marks{30,27,24,21,18,15,12,10,8,6,4,2};
        const auto reduction=processor.gainReduction.load();
        for (int i=0;i<12;++i) {
            const int x=241+28*i;
            label("-"+juce::String(marks[i]),x,17,28,14,12);
            const bool lit=reduction>=marks[i];
            const auto lens=juce::Rectangle<float>(float(x+2),40,23,12);
            g.setGradientFill({juce::Colour(lit?0xffff5645:0xff3f2023),0,40,
                               juce::Colour(lit?0xffb41d17:0xff200f12),0,52,false});
            g.fillRoundedRectangle(lens,1);
            g.setColour(juce::Colour(lit?0xfff88774:0xff4b292b));
            g.drawHorizontalLine(41,lens.getX()+2,lens.getRight()-2);
        }
        label("COMPRESSION",341,57,137,14,12);
        g.setColour(letters);
        for (int i=0;i<17;++i) {
            const float x=286.0f+11.0f*i;
            const float height=14.0f-0.63f*i;
            juce::Path mark;
            mark.startNewSubPath(x,111);
            mark.lineTo(x+9,111);
            mark.lineTo(x+9,110+height);
            mark.lineTo(x,111+height);
            mark.closeSubPath();
            g.fillPath(mark);
        }
        label("MORE >",465,110,66,15,12);
        label("LEVEL SET",613,16,94,16,12);
        label("-10",635,35,50,14,11);
        label("-20",591,61,45,14,11);
        label("0",680,61,33,14,11);
        label("-30",600,111,45,14,11);
        label("+10",681,111,41,14,11);
        for (int i=0;i<9;++i) {
            const float angle=-2.26f+4.52f*i/8;
            const juce::Point<float> direction(std::sin(angle),-std::cos(angle));
            const juce::Point<float> center(660,84.5f);
            g.drawLine({center+direction*26.0f,center+direction*(i%2==0?36.0f:32.0f)},1.3f);
        }
        label("HI-Z",718,16,85,13,11);
        label("INPUT",718,29,85,13,11);
        g.setColour(juce::Colour(0xff121214));
        g.fillEllipse(735,58,53,53);
        juce::Path nut;
        nut.addPolygon({761.5f,84.5f},6,22.5f,0.0f);
        g.setGradientFill({juce::Colour(0xffeee6d6),749,62,
                           juce::Colour(0xff8d857b),776,101,false});
        g.fillPath(nut);
        g.setColour(juce::Colour(0xffc1b9aa));
        g.drawEllipse(744,67,35,35,3);
        g.setColour(juce::Colour(0xff100f12));
        g.fillEllipse(747,70,29,29);
        g.setColour(juce::Colour(0xff5b564f));
        g.drawEllipse(744,67,35,35,1.5f);
        label("OVER EASY COMPRESSOR/LIMITER",250,145,325,17,13);
    }

private:
    class TrimItem final : public juce::PopupMenu::CustomComponent {
    public:
        TrimItem(juce::AudioProcessorValueTreeState& state,const juce::String& id,const juce::String& name)
            : juce::PopupMenu::CustomComponent(false) {
            label.setText(name,juce::dontSendNotification);
            slider.setSliderStyle(juce::Slider::LinearHorizontal);
            slider.setTextBoxStyle(juce::Slider::TextBoxRight,false,75,24);
            slider.setTextValueSuffix(" dB");
            addAndMakeVisible(label);addAndMakeVisible(slider);
            attachment=std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(state,id,slider);
            slider.setDoubleClickReturnValue(true,0.0);
        }
        void getIdealSize(int& w,int& h) override {w=310;h=38;}
        void resized() override {auto area=getLocalBounds().reduced(8,3);label.setBounds(area.removeFromLeft(100));slider.setBounds(area);}
    private:
        juce::Label label;
        juce::Slider slider;
        std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> attachment;
    };
    class Face final : public juce::LookAndFeel_V4 {
        void drawLinearSlider(juce::Graphics& g,int x,int y,int width,int height,float pos,float,float,
                              juce::Slider::SliderStyle,juce::Slider&) override {
            g.setColour(juce::Colour(0xff111014));
            g.fillRoundedRectangle(float(x+5),float(y+height/2-3),float(width-10),6,3);
            const auto cap=juce::Rectangle<float>(pos-15,float(y+2),30,float(height-4));
            g.setGradientFill({juce::Colour(0xff49474c),cap.getX(),cap.getY(),
                               juce::Colour(0xff131215),cap.getX(),cap.getBottom(),false});
            g.fillRoundedRectangle(cap,2);
            g.setColour(juce::Colour(0xffd6d1c5));
            g.drawVerticalLine(static_cast<int>(pos),cap.getY()+2,cap.getBottom()-3);
        }

        void drawRotarySlider(juce::Graphics& g,int x,int y,int width,int height,float pos,float,float,
                              juce::Slider&) override {
            const juce::Point<float> center(x+width/2.0f,y+height/2.0f);
            const auto circle=[&](float r) {return juce::Rectangle<float>(2*r,2*r).withCentre(center);};
            g.setColour(juce::Colour(0xff0d0c0f));
            g.fillEllipse(circle(23));
            g.setColour(juce::Colour(0xff3c3940));
            g.drawEllipse(circle(22),1);
            const auto radial=[&](float radius,float a) {return center+juce::Point<float>{std::sin(a),-std::cos(a)}*radius;};
            for (int i=0;i<40;++i) {
                const auto a=float(i)*0.15707963f;
                g.drawLine({radial(18,a),radial(21,a)},1.0f);
            }
            const float a=-2.26f+4.52f*pos;
            g.setColour(juce::Colour(0xffe9e5d9));
            g.drawLine({radial(9,a),radial(20,a)},1.4f);
        }
    };
    void timerCallback() override {repaint();}
    using Attachment=juce::AudioProcessorValueTreeState::SliderAttachment;
    Compressor& processor;
    Face face;
    juce::Slider compression,level;
    juce::ToggleButton noiseButton;
    juce::TextButton settings;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ButtonAttachment> noiseAttachment;
    std::unique_ptr<Attachment> compressionAttachment,levelAttachment;
};

juce::AudioProcessorEditor* Compressor::createEditor() {return new Panel(*this);}
}
juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() {return new Compressor;}
